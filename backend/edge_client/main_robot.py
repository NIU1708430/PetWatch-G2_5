import base64
import time
import os
import subprocess
import cv2
import threading # 🔴 Importante para los FPS
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

# ====================================================================
# 🔴 HILO PARALELO: CAPTURA DE CÁMARA ZERO-LAG
# ====================================================================
class CameraStream:
    def __init__(self):
        self.picam2 = Picamera2()
        self.picam2.configure(self.picam2.create_video_configuration(
            main={"format": "RGB888", "size": (ANCHO, ALTO)}
        ))
        self.frame = None
        self.running = False
        self.lock = threading.Lock()

    def start(self):
        self.picam2.start()
        self.running = True
        self.thread = threading.Thread(target=self.update, args=())
        self.thread.daemon = True
        self.thread.start()
        return self

    def update(self):
        while self.running:
            try:
                img = self.picam2.capture_array("main")
                with self.lock:
                    self.frame = img
            except Exception:
                pass
            time.sleep(0.001)

    def read(self):
        with self.lock:
            return self.frame

    def stop(self):
        self.running = False
        self.thread.join()
        self.picam2.stop()


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
                    
                    print(f"-> Volviendo a la posición inicial ({ANGULO_INICIAL}°)")
                    set_angulo(ANGULO_INICIAL)
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
                        set_angulo(45)
                        time.sleep(1.5)
                        set_angulo(ANGULO_INICIAL)
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
    print("   PETWATCH CLOUD - TRANSMISIÓN MULTIHILO (FPS+)  ")
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

    # 3. Inicialización de Picamera2 EN PARALELO
    print("Iniciando flujo paralelo de Picamera2...")
    camara_stream = CameraStream().start()
    time.sleep(1.0) # Espera de seguridad para llenar el buffer

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
    print("--> Transmitiendo vídeo fluido a Google Pub/Sub.")
    print("--> Escuchando Firestore para el amplificador I2S y Motores.")
    print("--> Para apagar de forma segura, pulsa Ctrl + C.")
    print("==================================================\n")

    ultimo_envio_ia = 0.0

    try:
        while True:
            # Capturar fotograma instantáneo del hilo paralelo
            frame_bgr = camara_stream.read()
            if frame_bgr is None:
                continue

            tiempo_actual = time.time()
            if tiempo_actual - ultimo_envio_ia >= 0.1: # 🔴 ENVÍO CADA 0.1s (~10 FPS TEÓRICOS)
                
                # 🔴 REDUCCIÓN DE CALIDAD AL 50% PARA ALIGERAR LA SUBIDA
                _, buffer = cv2.imencode('.jpg', frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 50])
                img_bytes = buffer.tobytes()

                try:
                    # En lugar de bloquear la consola con prints, publicamos en silencio
                    publisher.publish(topic_path, img_bytes)
                    ultimo_envio_ia = tiempo_actual
                except Exception as pub_error:
                    pass # Ocultamos los errores de timeout para no frenar el bucle

            time.sleep(0.001)

    except KeyboardInterrupt:
        print("\n\n🛑 [SISTEMA] Solicitud de apagado manual detectada.")
    finally:
        print("Cerrando recursos del robot de manera segura...")
        camara_stream.stop()
        servo.stop()
        GPIO.cleanup()
        print("¡Cámara liberada e hilos cerrados correctamente. Robot en reposo!")


if __name__ == "__main__":
    main()