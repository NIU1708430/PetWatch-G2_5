import base64
import time
import os
import subprocess
import cv2
import threading
from google.cloud import pubsub_v1
from google.cloud import firestore
from picamera2 import Picamera2
from datetime import datetime, timezone, timedelta

# ====================================================================
# CONFIGURACIÓN DEL HARDWARE (RPi.GPIO para Servomotor)
# ====================================================================
import RPi.GPIO as GPIO

PIN_SERVO = 4
GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN_SERVO, GPIO.OUT)

# Iniciamos el PWM en el pin 4 a 50Hz
servo = GPIO.PWM(PIN_SERVO, 50) 
servo.start(0) 

def set_angulo(angulo):
    duty = (angulo / 18) + 2
    servo.ChangeDutyCycle(duty)

def soltar_motor():
    servo.ChangeDutyCycle(0)

# Fijar ángulo inicial
ANGULO_INICIAL = 190 
print(f"🔧 Ajustando dispensador a su posición inicial: {ANGULO_INICIAL}°")
set_angulo(ANGULO_INICIAL)
time.sleep(1.0)
soltar_motor()

# ================= CONFIGURACIÓN MASTER =================
PROJECT_ID = "petwatch-sm"
DATABASE_ID = "petwatch-db"
TOPIC_ID = "petwatch-video-stream"
RTSP_URL = "rtsp://localhost:8554/mascota"
ANCHO = 640
ALTO = 480
FPS = 30
# ========================================================

# ====================================================================
# 🔴 CLASE MULTIHILO PARA CÁMARA FLUIDA (Cero tirones)
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
    """ Escucha el botón de 'Dar Premio' de Firestore """
    for cambio in cambios:
        if cambio.type.name == 'ADDED':
            datos = cambio.document.to_dict()
            if datos.get('completado') is False:
                print("\n🦴 [MANUAL] ¡Comando manual recibido! Activando dispensador...")
                try:
                    print("-> Ángulo: 45° (Cerrando compuerta)")
                    set_angulo(45)
                    time.sleep(1.5)
                    
                    print(f"-> Volviendo a la posición inicial ({ANGULO_INICIAL}°)")
                    set_angulo(ANGULO_INICIAL)
                    time.sleep(1.5)

                    soltar_motor()
                    print("✅ [DISPENSADOR MANUAL] Premio entregado con éxito.")
                except Exception as servo_error:
                    print(f"❌ [DISPENSADOR MANUAL] Error: {servo_error}")

                cambio.document.reference.update({'completado': True})
                print("📌 [DATABASE] Comando marcado como leído.\n")


def reproducir_audio(documentos_totales, cambios, hora_lectura):
    """ Escucha los audios del Walkie-Talkie y los saca por el I2S """
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
                    with open(archivo_entrada, "wb") as f: f.write(bytes_audio)
                    try:
                        subprocess.run(['ffmpeg', '-i', archivo_entrada, '-acodec', 'pcm_s16le', '-ar', '44100', '-ac', '2', archivo_salida, '-y', '-loglevel', 'quiet'], check=True)
                        print("🔊 Reproduciendo...")
                        subprocess.run(['aplay', '-D', 'plughw:2,0', archivo_salida], check=True)
                        print("✅ [ALTAVOZ] Mensaje emitido.")
                    except Exception as e:
                        print(f"❌ [ALTAVOZ] Error: {e}")
                    finally:
                        if os.path.exists(archivo_entrada): os.remove(archivo_entrada)
                        if os.path.exists(archivo_salida): os.remove(archivo_salida)
                
                cambio.document.reference.update({'reproducido': True})


def main():
    print("==================================================")
    print(" 🚀 PETWATCH - ARQUITECTURA DE DOBLE VÍA (30 FPS) ")
    print("==================================================")

    print("Conectando con Google Cloud...")
    try:
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)
        db = firestore.Client(project=PROJECT_ID, database=DATABASE_ID)
        print("-> [OK] Conexiones Cloud establecidas.")
    except Exception as e:
        print(f"Error Cloud: {e}")
        return

    print("Iniciando flujo de cámara multihilo...")
    camara_stream = CameraStream().start()
    time.sleep(1.0) # Esperar a que se llene el primer frame en RAM

    print("Iniciando codificador FFmpeg H.264 (Tubería de vídeo)...")
    ffmpeg_cmd = [
        'ffmpeg', '-y',
        '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-pix_fmt', 'bgr24',                 
        '-s', f'{ANCHO}x{ALTO}', '-r', str(FPS),
        '-i', '-',                           
        '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency',
        '-an',                               
        '-f', 'rtsp', RTSP_URL               
    ]
    try:
        proceso_stream = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)
    except Exception as e:
        print(f"Error FFmpeg: {e}")
        return

    # Escuchadores de fondo
    print("📡 Activando escuchadores de Firestore (Audio y Motor)...")
    coleccion_audio_ref = db.collection("comandos_audio")
    observador_audio = coleccion_audio_ref.on_snapshot(reproducir_audio)
    
    coleccion_manual_ref = db.collection("comandos_servo")
    observador_manual = coleccion_manual_ref.on_snapshot(escuchar_comandos_manuales)

    print("\n✅ ¡SISTEMA ONLINE Y TRANSMITIENDO VÍDEO!")
    ultimo_envio_ia = 0.0

    try:
        while True:
            # Leemos el último frame de la RAM al instante
            frame_bgr = camara_stream.read()
            if frame_bgr is None: continue

            # --- VÍA 1: STREAMING DE VÍDEO EN DIRECTO (30 FPS hacia MediaMTX) ---
            try:
                proceso_stream.stdin.write(frame_bgr.tobytes())
            except Exception:
                pass

            # --- VÍA 2: TELEMETRÍA PARA LA IA (1 foto comprimida por segundo) ---
            tiempo_actual = time.time()
            if tiempo_actual - ultimo_envio_ia >= 1.0: 
                # Compresión fuerte (60%) para ahorrar red
                _, buffer = cv2.imencode('.jpg', frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
                try:
                    publisher.publish(topic_path, buffer.tobytes())
                    ultimo_envio_ia = tiempo_actual
                except Exception: 
                    pass

    except KeyboardInterrupt:
        print("\n🛑 Apagando...")
    finally:
        camara_stream.stop()
        if proceso_stream:
            proceso_stream.stdin.close()
            proceso_stream.wait()
        servo.stop()
        GPIO.cleanup()
        print("¡Hardware liberado!")

if __name__ == "__main__":
    main()