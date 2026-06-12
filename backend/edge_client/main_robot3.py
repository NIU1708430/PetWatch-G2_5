import base64
import time
import os
import subprocess
import cv2
import threading
from google.cloud import pubsub_v1
from google.cloud import firestore
from picamera2 import Picamera2

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
# 🔴 CLASE MULTIHILO: CONTROL DE CÁMARA Y STREAMING FFMPEG
# ====================================================================
class CameraStream:
    def __init__(self, ffmpeg_proc):
        self.picam2 = Picamera2()
        self.picam2.configure(self.picam2.create_video_configuration(
            main={"format": "RGB888", "size": (ANCHO, ALTO)}
        ))
        self.frame_bgr = None
        self.running = False
        self.lock = threading.Lock()
        self.ffmpeg_proc = ffmpeg_proc # Inyectamos el proceso de vídeo

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
                # 1. Capturamos al ritmo de hardware exacto de la cámara (30 FPS)
                frame_rgb = self.picam2.capture_array("main")
                
                # 2. Convertimos colores para que OpenCV y FFmpeg los entiendan
                frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
                
                # 3. Guardamos la foto en RAM para que la lea la Inteligencia Artificial
                with self.lock:
                    self.frame_bgr = frame_bgr
                
                # 4. 🔴 ENVIAMOS A FFMPEG EN ESTE HILO (30 veces por segundo exactas)
                if self.ffmpeg_proc:
                    self.ffmpeg_proc.stdin.write(frame_bgr.tobytes())
                    
            except Exception:
                pass

    def read(self):
        with self.lock:
            return self.frame_bgr

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
                    set_angulo(45)
                    time.sleep(1.5)
                    set_angulo(ANGULO_INICIAL)
                    time.sleep(1.5)
                    soltar_motor()
                    print("✅ [DISPENSADOR MANUAL] Premio entregado con éxito.")
                except Exception as servo_error:
                    print(f"❌ [DISPENSADOR MANUAL] Error: {servo_error}")

                cambio.document.reference.update({'completado': True})


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
    print(" 🚀 PETWATCH - VÍDEO 30FPS REAL + IA OPTIMIZADA   ")
    print("==================================================")

    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)
    db = firestore.Client(project=PROJECT_ID, database=DATABASE_ID)

    # 1. Arrancamos FFmpeg PRIMERO
    print("Iniciando codificador FFmpeg H.264...")
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

    # 2. Inyectamos FFmpeg en el hilo de la cámara para que vayan perfectamente sincronizados
    print("Iniciando cámara multihilo...")
    camara_stream = CameraStream(proceso_stream).start()
    time.sleep(1.0) 

    # Escuchadores
    db.collection("comandos_audio").on_snapshot(reproducir_audio)
    db.collection("comandos_servo").on_snapshot(escuchar_comandos_manuales)

    print("\n✅ ¡SISTEMA ONLINE Y TRANSMITIENDO VÍDEO FLUIDO!")
    ultimo_envio_ia = 0.0

    try:
        while True:
            # 🔴 BUCLE PRINCIPAL (Solo se ocupa de la Inteligencia Artificial)
            tiempo_actual = time.time()
            
            # Ajustado a 3 segundos para máximo ahorro de CPU y red.
            if tiempo_actual - ultimo_envio_ia >= 3.0: 
                frame_bgr = camara_stream.read()
                if frame_bgr is not None:
                    _, buffer = cv2.imencode('.jpg', frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
                    try:
                        publisher.publish(topic_path, buffer.tobytes())
                        ultimo_envio_ia = tiempo_actual
                    except Exception: 
                        pass
            
            # Ponemos a dormir al procesador 50 milisegundos para no quemar la Raspberry Pi
            time.sleep(0.05) 

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