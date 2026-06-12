import base64
import time
import os
import subprocess
import cv2
from google.cloud import pubsub_v1
from google.cloud import firestore
from picamera2 import Picamera2
# Imports de tiempo de forma global
from datetime import datetime, timezone, timedelta

# ====================================================================
# CONFIGURACIÓN DEL HARDWARE (Inyección de pines y motores vía RPi.GPIO)
# ====================================================================
import RPi.GPIO as GPIO

PIN_SERVO = 4
GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN_SERVO, GPIO.OUT)

# Iniciamos el PWM en el pin 4 a 50Hz (Frecuencia estándar para servos MG90S)
servo = GPIO.PWM(PIN_SERVO, 50) 
servo.start(0) # Iniciamos con ciclo de trabajo 0 (motor apagado y suelto)

# Funciones de conversión de Ángulo a Duty Cycle (Ciclo de trabajo)
def set_angulo(angulo):
    # La fórmula estándar para servos de 180 grados: (Ángulo / 18) + 2
    duty = (angulo / 18) + 2
    servo.ChangeDutyCycle(duty)

def soltar_motor():
    # Poner el duty a 0 relaja el motor, cortando la corriente y eliminando el jitter
    servo.ChangeDutyCycle(0)


# ====================================================================
# FIJAR EL ÁNGULO INICIAL AL ARRANCAR EL ROBOT
# ====================================================================
ANGULO_INICIAL = 190 
print(f"🔧 Ajustando dispensador a su posición inicial: {ANGULO_INICIAL}°")
set_angulo(ANGULO_INICIAL)
time.sleep(1.0)  # Le damos 1 segundo al motor para que llegue a la posición físicamente
soltar_motor()   # Cortamos la corriente para que no tiemble (Jitter) ni se caliente

# Variables de control para el dispensador (Conservadas para la IA)
ultimo_premio_tiempo = 0.0
COOLDOWN_PREMIOS = 30.0  # Segundos de espera para evitar saturación

# ================= CONFIGURACIÓN MASTER =================
PROJECT_ID = "petwatch-sm"
DATABASE_ID = "petwatch-db"
TOPIC_ID = "petwatch-video-stream"
ANCHO = 640
ALTO = 480
# ========================================================


def escuchar_comandos_manuales(documentos_totales, cambios, hora_lectura):
    """
    Se ejecuta AUTOMÁTICAMENTE cuando el usuario pulsa el botón 'Dar Premio' en la App.
    Ignora la IA y mueve el motor instantáneamente.
    """
    for cambio in cambios:
        if cambio.type.name == 'ADDED':
            datos = cambio.document.to_dict()
            
            if datos.get('completado') is False:
                print("\n🦴 [MANUAL] ¡Comando manual recibido desde la App! Activando dispensador...")
                try:
                    # Movimiento físico del dispensador
                    
                    
                    print("-> Ángulo: 45° (Cerrando compuerta)")
                    set_angulo(45)
                    time.sleep(1.5)
                    
                    print("-> Volviendo a la posición inicial (90°)")
                    set_angulo(190)
                    time.sleep(1.5)

                    # Relajamos el servo para que no consuma batería y evitar el jitter
                    soltar_motor()
                    print("✅ [DISPENSADOR MANUAL] Premio entregado con éxito.")
                    
                except Exception as servo_error:
                    print(f"❌ [DISPENSADOR MANUAL] Error al mover el motor: {servo_error}")

                # Marcamos como completado
                cambio.document.reference.update({'completado': True})
                print("📌 [DATABASE] Comando manual marcado como leído en Firestore.\n")


def reproducir_audio(documentos_totales, cambios, hora_lectura):
    """
    Se ejecuta AUTOMÁTIMAMENTE en un hilo secundario cada vez que entra 
    un audio nuevo desde la aplicación web de Flutter en Firestore.
    """
    for cambio in cambios:
        if cambio.type.name == 'ADDED':
            datos = cambio.document.to_dict()
            
            if datos.get('reproducido') is False:
                print("\n🎤 [ALTAVOZ] ¡Entrando audio desde la web PetWatch!")
                audio_b64 = datos.get('audio_b64')
                
                if audio_b64:
                    archivo_entrada = "mensaje_web.webm"
                    archivo_salida = "mensaje_robot.wav"
                    
                    bytes_audio = base64.b64decode(audio_b64)
                    with open(archivo_entrada, "wb") as archivo_webm:
                        archivo_webm.write(bytes_audio)
                    
                    try:
                        # --- CONVERSIÓN CON FFMPEG ---
                        subprocess.run([
                            'ffmpeg', '-i', archivo_entrada, 
                            '-acodec', 'pcm_s16le', '-ar', '44100', '-ac', '2',
                            archivo_salida, '-y', '-loglevel', 'quiet'
                        ], check=True)
                        
                        # --- REPRODUCCIÓN DIRECTA AL AMPLIFICADOR I2S ---
                        print("🔊 Enviando audio directo a los pines del amplificador (Tarjeta 2)...")
                        subprocess.run(['aplay', '-D', 'plughw:2,0', archivo_salida], check=True)
                        print("✅ [ALTAVOZ] Mensaje emitido correctamente por el hardware.")
                        
                    except subprocess.CalledProcessError:
                        print("❌ [ALTAVOZ] Error: FFMPEG o APLAY fallaron al procesar el archivo.")
                    except Exception as audio_error:
                        print(f"❌ [ALTAVOZ] Error crítico en la reproducción: {audio_error}")
                    finally:
                        if os.path.exists(archivo_entrada): os.remove(archivo_entrada)
                        if os.path.exists(archivo_salida): os.remove(archivo_salida)

                # Marcamos como reproducido
                cambio.document.reference.update({'reproducido': True})
                print("📌 [DATABASE] Documento marcado como leído en Firestore.\n")


# ====================================================================
# FUNCIONALIDAD IA APARTADA (Desactivada temporalmente)
# ====================================================================
def evaluar_premios(documentos_totales, cambios, hora_lectura):
    global ultimo_premio_tiempo
    for cambio in cambios:
        if cambio.type.name == 'ADDED':
            datos = cambio.document.to_dict()
            animal_detectado = str(datos.get("animal", "")).lower()
            postura_detectada = str(datos.get("postura", "")).upper()
            
            if animal_detectado in ["dog", "cat"] and postura_detectada == "SENTADO":
                tiempo_actual = time.time()
                if tiempo_actual - ultimo_premio_tiempo >= COOLDOWN_PREMIOS:
                    ultimo_premio_tiempo = tiempo_actual
                    print(f"\n🎁 [PIPELINE VALIDADO] Mascota identificada ({animal_detectado.upper()}) y confirmada SENTADA. ¡Dando premio!")
                    try:
                        print("-> Ángulo: 90° (Abriendo compuerta)")
                        set_angulo(90)
                        time.sleep(1.5)
                        print("-> Ángulo: 45° (Cerrando compuerta)")
                        set_angulo(45)
                        time.sleep(1.5)
                        print("Volviendo a la posi inicial")
                        set_angulo(90)
                        time.sleep(1.5)
                        soltar_motor()
                        print("✅ [DISPENSADOR] Ciclo de recompensa completado.")
                    except Exception as servo_error:
                        print(f"❌ [DISPENSADOR] Error en el control del motor: {servo_error}")
                else:
                    segundos_restantes = int(COOLDOWN_PREMIOS - (tiempo_actual - ultimo_premio_tiempo))
                    print(f"\r[INFO] Pipeline correcto, pero bloqueado por cooldown. Faltan {segundos_restantes}s.", end="", flush=True)


def main():
    print("==================================================")
    print("   PETWATCH CLOUD - SISTEMA 100% NATIVO EN NUBE   ")
    print("==================================================")

    # 1. Conexión con Google Cloud Pub/Sub (Vídeo Cloud)
    print("Conectando con Google Cloud Pub/Sub...")
    try:
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)
        print("-> [OK] Conexión Pub/Sub establecida.")
    except Exception as e:
        print(f"Error al conectar con Pub/Sub: {e}")
        return

    # 2. Conexión con Google Cloud Firestore (Audio y Motores)
    print("Conectando con Google Cloud Firestore...")
    try:
        db = firestore.Client(project=PROJECT_ID, database=DATABASE_ID)
        print("-> [OK] Conexión Firestore establecida.")
    except Exception as e:
        print(f"Error al conectar con Firestore: {e}")
        return

    # 3. Inicialización de Picamera2
    print("Iniciando Raspberry Pi Camera Module v2...")
    try:
        picam2 = Picamera2()
        picam2.configure(picam2.create_video_configuration(
            main={"format": "RGB888", "size": (ANCHO, ALTO)}
        ))
        picam2.start()
        print("-> [OK] Cámara v2 lista mediante Picamera2.")
    except Exception as cam_error:
        print(f"Error: No se pudo inicializar la cámara. {cam_error}")
        return

    # 4. Activar la Escucha de Audio en Tiempo Real (Segundo Plano)
    print("📡 [SISTEMA] Activando canal receptor de Walkie-Talkie...")
    coleccion_audio_ref = db.collection("comandos_audio")
    observador_audio = coleccion_audio_ref.on_snapshot(reproducir_audio)

    # 5. Activar la Escucha de Comandos Manuales de la App (Segundo Plano)
    print("📡 [SISTEMA] Activando receptor de comandos manuales de dispensador...")
    coleccion_manual_ref = db.collection("comandos_servo")
    observador_manual = coleccion_manual_ref.on_snapshot(escuchar_comandos_manuales)

    print("\n==================================================")
    print(" 🤖 [PETWATCH] ¡SISTEMA OPERATIVO Y CONECTADO! ")
    print("--> Transmitiendo vídeo directo a Google Pub/Sub.")
    print("--> Escuchando Firestore para el amplificador I2S.")
    print("--> Escuchando Firestore para el Botón Manual del Dispensador.")
    print("--> Para apagar de forma segura, pulsa Ctrl + C.")
    print("==================================================\n")

    ultimo_envio_ia = 0.0

    try:
        while True:
            # Capturar fotograma en memoria (Matriz RGB)
            frame_bgr = picam2.capture_array("main")

            # Envío de vídeo a la nube cada 0.2 segundos (Equivale a ~5 FPS estables)
            tiempo_actual = time.time()
            if tiempo_actual - ultimo_envio_ia >= 0.3:
                _, buffer = cv2.imencode('.jpg', frame_bgr)
                img_bytes = buffer.tobytes()

                try:
                    future = publisher.publish(topic_path, img_bytes)
                    print(f"\r[CLOUD VÍDEO] Transmitiendo fotograma activo... ID: {future.result()[:15]}...", end="", flush=True)
                    ultimo_envio_ia = tiempo_actual
                except Exception as pub_error:
                    print(f"\nError al enviar a Pub/Sub: {pub_error}")

            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\n\n🛑 [SISTEMA] Solicitud de apagado manual detectada.")
    finally:
        print("Cerrando recursos del robot de manera segura...")
        picam2.stop()
        servo.stop()
        GPIO.cleanup()
        print("¡Cámara liberada e hilos cerrados correctamente. Robot en reposo!")


if __name__ == "__main__":
    main()