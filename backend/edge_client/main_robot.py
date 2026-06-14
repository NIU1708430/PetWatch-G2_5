import base64
import time
import os
import subprocess
import cv2
from google.cloud import pubsub_v1
from google.cloud import firestore
from picamera2 import Picamera2
from datetime import datetime, timezone, timedelta
import RPi.GPIO as GPIO

# Configuracion de pines y motor (RPi.GPIO)
PIN_SERVO = 4
GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN_SERVO, GPIO.OUT)

# El motor MG90S funciona a una frecuencia estandar de 50Hz
servo = GPIO.PWM(PIN_SERVO, 50) 
servo.start(0) 

def set_angulo(angulo):
    # Formula para convertir el angulo (0-180) a ciclo de trabajo (duty cycle)
    duty = (angulo / 18) + 2
    servo.ChangeDutyCycle(duty)

def soltar_motor():
    # Cortar la senyal PWM (duty 0) evita que el motor vibre (jitter), 
    # se caliente y consuma bateria cuando no se esta moviendo
    servo.ChangeDutyCycle(0)

# Posicion inicial por defecto al arrancar el script
ANGULO_INICIAL = 190 
print(f"Ajustando dispensador a su posicion inicial: {ANGULO_INICIAL} grados")
set_angulo(ANGULO_INICIAL)
time.sleep(1.0)  
soltar_motor()   

# Timers de control para evitar comportamientos no deseados
ultimo_premio_tiempo = 0.0
COOLDOWN_PREMIOS = 30.0  

ultimo_audio_tiempo = 0.0 
VENTANA_OBEDIENCIA = 15.0 

# Credenciales y parametros de la camara
PROJECT_ID = "petwatch-sm"
DATABASE_ID = "petwatch-db"
TOPIC_ID = "petwatch-video-stream"
ANCHO = 640
ALTO = 480


def escuchar_comandos_manuales(documentos_totales, cambios, hora_lectura):
    # Se dispara cuando el usuario pulsa el boton en la app. Ignora a la IA.
    for cambio in cambios:
        if cambio.type.name == 'ADDED':
            datos = cambio.document.to_dict()
            
            if datos.get('completado') is False:
                print("\n[MANUAL] Comando recibido desde la App. Activando dispensador...")
                try:
                    set_angulo(45)
                    time.sleep(1.5)
                    
                    set_angulo(ANGULO_INICIAL)
                    time.sleep(1.5)

                    soltar_motor()
                    print("[DISPENSADOR MANUAL] Premio entregado con exito.")
                except Exception as servo_error:
                    print(f"[DISPENSADOR MANUAL] Error al mover el motor: {servo_error}")

                # Es vital marcarlo como true para que si se reinicia el script no vuelva a tirar el premio
                cambio.document.reference.update({'completado': True})
                print("[DATABASE] Comando manual marcado como leido.")


def reproducir_audio(documentos_totales, cambios, hora_lectura):
    # Listener para descargar, convertir y reproducir notas de voz
    global ultimo_audio_tiempo
    for cambio in cambios:
        if cambio.type.name == 'ADDED':
            datos = cambio.document.to_dict()
            
            if datos.get('reproducido') is False:
                print("\n[ALTAVOZ] Entrando audio desde la web PetWatch")
                audio_b64 = datos.get('audio_b64')
                
                if audio_b64:
                    archivo_entrada = "mensaje_web.webm"
                    archivo_salida = "mensaje_robot.wav"
                    
                    # El audio llega codificado en texto, hay que pasarlo a bytes fisicos
                    bytes_audio = base64.b64decode(audio_b64)
                    with open(archivo_entrada, "wb") as archivo_webm:
                        archivo_webm.write(bytes_audio)
                    
                    try:
                        # Forzamos la conversion a PCM 44100Hz para compatibilidad con el DAC I2S
                        subprocess.run(['ffmpeg', '-i', archivo_entrada, '-acodec', 'pcm_s16le', '-ar', '44100', '-ac', '2', archivo_salida, '-y', '-loglevel', 'quiet'], check=True)
                        print("Reproduciendo audio...")
                        subprocess.run(['aplay', '-D', 'plughw:2,0', archivo_salida], check=True)
                        print("[ALTAVOZ] Mensaje emitido.")
                        
                        # Al hablar, abrimos la ventana de tiempo para que la mascota obedezca
                        ultimo_audio_tiempo = time.time()
                        print(f"[ADIESTRAMIENTO] La mascota tiene {VENTANA_OBEDIENCIA} segundos para sentarse.")
                        
                    except Exception as e:
                        print(f"[ALTAVOZ] Error en la reproduccion: {e}")
                    finally:
                        if os.path.exists(archivo_entrada): os.remove(archivo_entrada)
                        if os.path.exists(archivo_salida): os.remove(archivo_salida)

                cambio.document.reference.update({'reproducido': True})


def evaluar_premios(documentos_totales, cambios, hora_lectura):
    # Logica core del adiestramiento. Junta la lectura de la IA con el estado del altavoz.
    global ultimo_premio_tiempo, ultimo_audio_tiempo
    
    for cambio in cambios:
        if cambio.type.name == 'ADDED':
            datos = cambio.document.to_dict()
            animal_detectado = str(datos.get("animal", "")).lower()
            postura_detectada = str(datos.get("postura", "")).upper()
            
            if animal_detectado in ["dog", "cat"] and postura_detectada == "SENTADO":
                tiempo_actual = time.time()
                
                # Comprueba si el animal se ha sentado a raiz de una orden reciente de voz
                if (tiempo_actual - ultimo_audio_tiempo) <= VENTANA_OBEDIENCIA:
                    
                    # Comprueba si el motor esta listo para usarse
                    if tiempo_actual - ultimo_premio_tiempo >= COOLDOWN_PREMIOS:
                        ultimo_premio_tiempo = tiempo_actual
                        
                        # Anulamos la ventana actual para evitar dobles premios por la misma orden
                        ultimo_audio_tiempo = 0.0 
                        
                        print(f"\n[IA] {animal_detectado.upper()} obedecio tu comando y esta SENTADO. Dando premio...")
                        try:
                            set_angulo(90)
                            time.sleep(1.5)
                            set_angulo(45)
                            time.sleep(1.5)
                            set_angulo(ANGULO_INICIAL)
                            time.sleep(1.5)
                            soltar_motor()
                            print("[DISPENSADOR] Recompensa entregada.")
                        except Exception as servo_error:
                            print(f"[DISPENSADOR] Error mecanico: {servo_error}")
                    else:
                        segundos = int(COOLDOWN_PREMIOS - (tiempo_actual - ultimo_premio_tiempo))
                        print(f"\r[INFO] Mascota sentada, pero dispensador en cooldown. Faltan {segundos}s.", end="", flush=True)


def main():
    print("Iniciando PETWATCH Edge Node...")

    print("Conectando con Google Cloud Pub/Sub...")
    try:
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)
    except Exception as e:
        print(f"Error critico en Pub/Sub: {e}")
        return

    print("Conectando con Google Cloud Firestore...")
    try:
        db = firestore.Client(project=PROJECT_ID, database=DATABASE_ID)
    except Exception as e:
        print(f"Error critico en Firestore: {e}")
        return

    print("Inicializando hardware de camara...")
    try:
        picam2 = Picamera2()
        picam2.configure(picam2.create_video_configuration(
            main={"format": "RGB888", "size": (ANCHO, ALTO)}
        ))
        picam2.start()
    except Exception as cam_error:
        print(f"Error al levantar Picamera2: {cam_error}")
        return

    # Registramos los callbacks para que Firestore trabaje de fondo mediante hilos
    db.collection("comandos_audio").on_snapshot(reproducir_audio)
    db.collection("comandos_servo").on_snapshot(escuchar_comandos_manuales)
    db.collection("historial_mascotas").on_snapshot(evaluar_premios)

    print("Sistema operativo. Transmitiendo telemetria y esperando eventos...")

    ultimo_envio_ia = 0.0

    try:
        while True:
            # Captura raw a la memoria RAM de la Pi
            frame_bgr = picam2.capture_array("main")

            # Limitador de subida a ~5 FPS para no colapsar la red ni agotar la cuota de Google Cloud
            tiempo_actual = time.time()
            if tiempo_actual - ultimo_envio_ia >= 0.2:
                # Comprimir a JPG es obligatorio para que el payload quepa en los limites de Pub/Sub
                _, buffer = cv2.imencode('.jpg', frame_bgr)
                img_bytes = buffer.tobytes()

                try:
                    future = publisher.publish(topic_path, img_bytes)
                    print(f"\r[VÍDEO] Subiendo frame... ID: {future.result()[:15]}...", end="", flush=True)
                    ultimo_envio_ia = tiempo_actual
                except Exception as pub_error:
                    print(f"\nError de subida a Pub/Sub: {pub_error}")

            # Previene que el bucle while sature el 100% de la CPU
            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\nApagado manual detectado (Ctrl+C).")
    finally:
        print("Limpiando recursos GPIO y cerrando camara...")
        picam2.stop()
        servo.stop()
        GPIO.cleanup()
        print("Apagado completado.")

if __name__ == "__main__":
    main()



# main_robot.py sense evaluar recompensa impelmentat


# import base64
# import time
# import os
# import subprocess
# import cv2
# from google.cloud import pubsub_v1
# from google.cloud import firestore
# from picamera2 import Picamera2
# # Imports de tiempo de forma global
# from datetime import datetime, timezone, timedelta

# # ====================================================================
# # CONFIGURACIÓN DEL HARDWARE (Inyección de pines y motores vía RPi.GPIO)
# # ====================================================================
# import RPi.GPIO as GPIO

# PIN_SERVO = 4
# GPIO.setmode(GPIO.BCM)
# GPIO.setup(PIN_SERVO, GPIO.OUT)

# # Iniciamos el PWM en el pin 4 a 50Hz (Frecuencia estándar para servos MG90S)
# servo = GPIO.PWM(PIN_SERVO, 50) 
# servo.start(0) # Iniciamos con ciclo de trabajo 0 (motor apagado y suelto)

# # Funciones de conversión de Ángulo a Duty Cycle (Ciclo de trabajo)
# def set_angulo(angulo):
#     # La fórmula estándar para servos de 180 grados: (Ángulo / 18) + 2
#     duty = (angulo / 18) + 2
#     servo.ChangeDutyCycle(duty)

# def soltar_motor():
#     # Poner el duty a 0 relaja el motor, cortando la corriente y eliminando el jitter
#     servo.ChangeDutyCycle(0)


# # ====================================================================
# # FIJAR EL ÁNGULO INICIAL AL ARRANCAR EL ROBOT
# # ====================================================================
# ANGULO_INICIAL = 190 
# print(f"🔧 Ajustando dispensador a su posición inicial: {ANGULO_INICIAL}°")
# set_angulo(ANGULO_INICIAL)
# time.sleep(1.0)  # Le damos 1 segundo al motor para que llegue a la posición físicamente
# soltar_motor()   # Cortamos la corriente para que no tiemble (Jitter) ni se caliente

# # Variables de control para el dispensador (Conservadas para la IA)
# ultimo_premio_tiempo = 0.0
# COOLDOWN_PREMIOS = 30.0  # Segundos de espera para evitar saturación

# # ================= CONFIGURACIÓN MASTER =================
# PROJECT_ID = "petwatch-sm"
# DATABASE_ID = "petwatch-db"
# TOPIC_ID = "petwatch-video-stream"
# ANCHO = 640
# ALTO = 480
# # ========================================================


# def escuchar_comandos_manuales(documentos_totales, cambios, hora_lectura):
#     """
#     Se ejecuta AUTOMÁTICAMENTE cuando el usuario pulsa el botón 'Dar Premio' en la App.
#     Ignora la IA y mueve el motor instantáneamente.
#     """
#     for cambio in cambios:
#         if cambio.type.name == 'ADDED':
#             datos = cambio.document.to_dict()
            
#             if datos.get('completado') is False:
#                 print("\n🦴 [MANUAL] ¡Comando manual recibido desde la App! Activando dispensador...")
#                 try:
#                     # Movimiento físico del dispensador
                    
                    
#                     print("-> Ángulo: 45° (Cerrando compuerta)")
#                     set_angulo(45)
#                     time.sleep(1.5)
                    
#                     print("-> Volviendo a la posición inicial (90°)")
#                     set_angulo(190)
#                     time.sleep(1.5)

#                     # Relajamos el servo para que no consuma batería y evitar el jitter
#                     soltar_motor()
#                     print("✅ [DISPENSADOR MANUAL] Premio entregado con éxito.")
                    
#                 except Exception as servo_error:
#                     print(f"❌ [DISPENSADOR MANUAL] Error al mover el motor: {servo_error}")

#                 # Marcamos como completado
#                 cambio.document.reference.update({'completado': True})
#                 print("📌 [DATABASE] Comando manual marcado como leído en Firestore.\n")


# def reproducir_audio(documentos_totales, cambios, hora_lectura):
#     """
#     Se ejecuta AUTOMÁTIMAMENTE en un hilo secundario cada vez que entra 
#     un audio nuevo desde la aplicación web de Flutter en Firestore.
#     """
#     for cambio in cambios:
#         if cambio.type.name == 'ADDED':
#             datos = cambio.document.to_dict()
            
#             if datos.get('reproducido') is False:
#                 print("\n🎤 [ALTAVOZ] ¡Entrando audio desde la web PetWatch!")
#                 audio_b64 = datos.get('audio_b64')
                
#                 if audio_b64:
#                     archivo_entrada = "mensaje_web.webm"
#                     archivo_salida = "mensaje_robot.wav"
                    
#                     bytes_audio = base64.b64decode(audio_b64)
#                     with open(archivo_entrada, "wb") as archivo_webm:
#                         archivo_webm.write(bytes_audio)
                    
#                     try:
#                         # --- CONVERSIÓN CON FFMPEG ---
#                         subprocess.run([
#                             'ffmpeg', '-i', archivo_entrada, 
#                             '-acodec', 'pcm_s16le', '-ar', '44100', '-ac', '2',
#                             archivo_salida, '-y', '-loglevel', 'quiet'
#                         ], check=True)
                        
#                         # --- REPRODUCCIÓN DIRECTA AL AMPLIFICADOR I2S ---
#                         print("🔊 Enviando audio directo a los pines del amplificador (Tarjeta 2)...")
#                         subprocess.run(['aplay', '-D', 'plughw:2,0', archivo_salida], check=True)
#                         print("✅ [ALTAVOZ] Mensaje emitido correctamente por el hardware.")
                        
#                     except subprocess.CalledProcessError:
#                         print("❌ [ALTAVOZ] Error: FFMPEG o APLAY fallaron al procesar el archivo.")
#                     except Exception as audio_error:
#                         print(f"❌ [ALTAVOZ] Error crítico en la reproducción: {audio_error}")
#                     finally:
#                         if os.path.exists(archivo_entrada): os.remove(archivo_entrada)
#                         if os.path.exists(archivo_salida): os.remove(archivo_salida)

#                 # Marcamos como reproducido
#                 cambio.document.reference.update({'reproducido': True})
#                 print("📌 [DATABASE] Documento marcado como leído en Firestore.\n")


# # ====================================================================
# # FUNCIONALIDAD IA APARTADA (Desactivada temporalmente)
# # ====================================================================
# def evaluar_premios(documentos_totales, cambios, hora_lectura):
#     global ultimo_premio_tiempo
#     for cambio in cambios:
#         if cambio.type.name == 'ADDED':
#             datos = cambio.document.to_dict()
#             animal_detectado = str(datos.get("animal", "")).lower()
#             postura_detectada = str(datos.get("postura", "")).upper()
            
#             if animal_detectado in ["dog", "cat"] and postura_detectada == "SENTADO":
#                 tiempo_actual = time.time()
#                 if tiempo_actual - ultimo_premio_tiempo >= COOLDOWN_PREMIOS:
#                     ultimo_premio_tiempo = tiempo_actual
#                     print(f"\n🎁 [PIPELINE VALIDADO] Mascota identificada ({animal_detectado.upper()}) y confirmada SENTADA. ¡Dando premio!")
#                     try:
#                         print("-> Ángulo: 90° (Abriendo compuerta)")
#                         set_angulo(90)
#                         time.sleep(1.5)
#                         print("-> Ángulo: 45° (Cerrando compuerta)")
#                         set_angulo(45)
#                         time.sleep(1.5)
#                         print("Volviendo a la posi inicial")
#                         set_angulo(90)
#                         time.sleep(1.5)
#                         soltar_motor()
#                         print("✅ [DISPENSADOR] Ciclo de recompensa completado.")
#                     except Exception as servo_error:
#                         print(f"❌ [DISPENSADOR] Error en el control del motor: {servo_error}")
#                 else:
#                     segundos_restantes = int(COOLDOWN_PREMIOS - (tiempo_actual - ultimo_premio_tiempo))
#                     print(f"\r[INFO] Pipeline correcto, pero bloqueado por cooldown. Faltan {segundos_restantes}s.", end="", flush=True)


# def main():
#     print("==================================================")
#     print("   PETWATCH CLOUD - SISTEMA 100% NATIVO EN NUBE   ")
#     print("==================================================")

#     # 1. Conexión con Google Cloud Pub/Sub (Vídeo Cloud)
#     print("Conectando con Google Cloud Pub/Sub...")
#     try:
#         publisher = pubsub_v1.PublisherClient()
#         topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)
#         print("-> [OK] Conexión Pub/Sub establecida.")
#     except Exception as e:
#         print(f"Error al conectar con Pub/Sub: {e}")
#         return

#     # 2. Conexión con Google Cloud Firestore (Audio y Motores)
#     print("Conectando con Google Cloud Firestore...")
#     try:
#         db = firestore.Client(project=PROJECT_ID, database=DATABASE_ID)
#         print("-> [OK] Conexión Firestore establecida.")
#     except Exception as e:
#         print(f"Error al conectar con Firestore: {e}")
#         return

#     # 3. Inicialización de Picamera2
#     print("Iniciando Raspberry Pi Camera Module v2...")
#     try:
#         picam2 = Picamera2()
#         picam2.configure(picam2.create_video_configuration(
#             main={"format": "RGB888", "size": (ANCHO, ALTO)}
#         ))
#         picam2.start()
#         print("-> [OK] Cámara v2 lista mediante Picamera2.")
#     except Exception as cam_error:
#         print(f"Error: No se pudo inicializar la cámara. {cam_error}")
#         return

#     # 4. Activar la Escucha de Audio en Tiempo Real (Segundo Plano)
#     print("📡 [SISTEMA] Activando canal receptor de Walkie-Talkie...")
#     coleccion_audio_ref = db.collection("comandos_audio")
#     observador_audio = coleccion_audio_ref.on_snapshot(reproducir_audio)

#     # 5. Activar la Escucha de Comandos Manuales de la App (Segundo Plano)
#     print("📡 [SISTEMA] Activando receptor de comandos manuales de dispensador...")
#     coleccion_manual_ref = db.collection("comandos_servo")
#     observador_manual = coleccion_manual_ref.on_snapshot(escuchar_comandos_manuales)

#     print("\n==================================================")
#     print(" 🤖 [PETWATCH] ¡SISTEMA OPERATIVO Y CONECTADO! ")
#     print("--> Transmitiendo vídeo directo a Google Pub/Sub.")
#     print("--> Escuchando Firestore para el amplificador I2S.")
#     print("--> Escuchando Firestore para el Botón Manual del Dispensador.")
#     print("--> Para apagar de forma segura, pulsa Ctrl + C.")
#     print("==================================================\n")

#     ultimo_envio_ia = 0.0

#     try:
#         while True:
#             # Capturar fotograma en memoria (Matriz RGB)
#             frame_bgr = picam2.capture_array("main")

#             # Envío de vídeo a la nube cada 0.2 segundos (Equivale a ~5 FPS estables)
#             tiempo_actual = time.time()
#             if tiempo_actual - ultimo_envio_ia >= 0.2:
#                 _, buffer = cv2.imencode('.jpg', frame_bgr)
#                 img_bytes = buffer.tobytes()

#                 try:
#                     future = publisher.publish(topic_path, img_bytes)
#                     print(f"\r[CLOUD VÍDEO] Transmitiendo fotograma activo... ID: {future.result()[:15]}...", end="", flush=True)
#                     ultimo_envio_ia = tiempo_actual
#                 except Exception as pub_error:
#                     print(f"\nError al enviar a Pub/Sub: {pub_error}")

#             time.sleep(0.01)

#     except KeyboardInterrupt:
#         print("\n\n🛑 [SISTEMA] Solicitud de apagado manual detectada.")
#     finally:
#         print("Cerrando recursos del robot de manera segura...")
#         picam2.stop()
#         servo.stop()
#         GPIO.cleanup()
#         print("¡Cámara liberada e hilos cerrados correctamente. Robot en reposo!")


# if __name__ == "__main__":
#     main()