import base64
import time
import os
import subprocess
import cv2
import threading
import numpy as np
from google.cloud import pubsub_v1
from google.cloud import firestore
from picamera2 import Picamera2

# Forzamos lgpio para evitar conflictos de hardware con gpiozero
os.environ["GPIOZERO_PIN_FACTORY"] = "lgpio"
import RPi.GPIO as GPIO
from gpiozero import PhaseEnableMotor, DistanceSensor

# ====================================================================
# CONFIGURACIÓN DEL HARDWARE
# ====================================================================
# 1. Dispensador de Premios (Servo PWM)
PIN_SERVO = 4
GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN_SERVO, GPIO.OUT)
servo = GPIO.PWM(PIN_SERVO, 50) 
servo.start(0) 

def set_angulo(angulo):
    duty = (angulo / 18) + 2
    servo.ChangeDutyCycle(duty)

def soltar_motor():
    servo.ChangeDutyCycle(0)

ANGULO_INICIAL = 190 
set_angulo(ANGULO_INICIAL)
time.sleep(1.0)
soltar_motor()

# 2. Motores L298N (DRI0002)
motor_izquierdo = PhaseEnableMotor(phase=17, enable=13)
motor_derecho = PhaseEnableMotor(phase=22, enable=27)

def avanzar(velocidad=1.0):
    motor_izquierdo.forward(velocidad)
    motor_derecho.forward(velocidad)

def girar_izquierda(velocidad=1.0):
    motor_izquierdo.backward(velocidad)
    motor_derecho.forward(velocidad)

def girar_derecha(velocidad=1.0):
    motor_izquierdo.forward(velocidad)
    motor_derecho.backward(velocidad)

def detener():
    motor_izquierdo.stop()
    motor_derecho.stop()

def fijar_velocidades(vel_izq, vel_der):
    if vel_izq >= 0: motor_izquierdo.forward(vel_izq)
    else: motor_izquierdo.backward(abs(vel_izq))
    if vel_der >= 0: motor_derecho.forward(vel_der)
    else: motor_derecho.backward(abs(vel_der))

# 3. Sensores Ultrasónicos HC-SR04
class HCSR04:
    def __init__(self, trigger_pin, echo_pin):
        self._sensor = DistanceSensor(echo=echo_pin, trigger=trigger_pin, max_distance=4.0)
    def distance_cm(self):
        return self._sensor.distance * 100

sensor_cen = HCSR04(trigger_pin=5, echo_pin=6)
sensor_der = HCSR04(trigger_pin=26, echo_pin=12) 
sensor_izq = HCSR04(trigger_pin=23, echo_pin=24)

# ================= CONFIGURACIÓN MASTER =================
PROJECT_ID = "petwatch-sm"
DATABASE_ID = "petwatch-db"
TOPIC_ID = "petwatch-video-stream"
ANCHO = 640
ALTO = 480
VEL_BASE = 0.8
DIST_FRENTE_MIN = 25.0
DIST_PARED_MIN = 20.0
DIST_PARED_MAX = 25.0
# ========================================================

# ====================================================================
# 🔴 HILO DE CÁMARA (Para no frenar a los motores)
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
                img_rgb = self.picam2.capture_array("main")
                img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
                with self.lock:
                    self.frame = img_bgr
            except Exception:
                pass
            time.sleep(0.01)

    def read(self):
        with self.lock:
            return self.frame

    def stop(self):
        self.running = False
        self.thread.join()
        self.picam2.stop()


def escuchar_comandos_manuales(doc_totales, cambios, hora_lectura):
    for cambio in cambios:
        if cambio.type.name == 'ADDED':
            datos = cambio.document.to_dict()
            if datos.get('completado') is False:
                print("\n🦴 [MANUAL] ¡Dispensando premio!")
                try:
                    set_angulo(45)
                    time.sleep(1.5)
                    set_angulo(ANGULO_INICIAL)
                    time.sleep(1.5)
                    soltar_motor()
                except Exception as e:
                    pass
                cambio.document.reference.update({'completado': True})

def reproducir_audio(doc_totales, cambios, hora_lectura):
    for cambio in cambios:
        if cambio.type.name == 'ADDED':
            datos = cambio.document.to_dict()
            if datos.get('reproducido') is False:
                print("\n🎤 [ALTAVOZ] ¡Reproduciendo audio!")
                audio_b64 = datos.get('audio_b64')
                if audio_b64:
                    archivo_entrada = "mensaje_web.webm"
                    archivo_salida = "mensaje_robot.wav"
                    with open(archivo_entrada, "wb") as f: f.write(base64.b64decode(audio_b64))
                    try:
                        subprocess.run(['ffmpeg', '-i', archivo_entrada, '-acodec', 'pcm_s16le', '-ar', '44100', '-ac', '2', archivo_salida, '-y', '-loglevel', 'quiet'], check=True)
                        subprocess.run(['aplay', '-D', 'plughw:2,0', archivo_salida], check=True)
                    except Exception: pass
                    finally:
                        if os.path.exists(archivo_entrada): os.remove(archivo_entrada)
                        if os.path.exists(archivo_salida): os.remove(archivo_salida)
                cambio.document.reference.update({'reproducido': True})


def main():
    print("==================================================")
    print(" 🤖 PETWATCH - IA AUTÓNOMA + NAVEGACIÓN ACTIVA")
    print("==================================================")

    print("Cargando IA de visión local (MobileNet-SSD)...")
    try:
        net = cv2.dnn.readNetFromCaffe("MobileNetSSD_deploy.prototxt", "MobileNetSSD_deploy.caffemodel")
    except Exception as e:
        print(f"Error: Faltan los archivos de MobileNet-SSD. Ejecuta los comandos wget primero.\n{e}")
        return

    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)
    db = firestore.Client(project=PROJECT_ID, database=DATABASE_ID)

    camara_stream = CameraStream().start()
    time.sleep(1.0)

    db.collection("comandos_audio").on_snapshot(reproducir_audio)
    db.collection("comandos_servo").on_snapshot(escuchar_comandos_manuales)

    print("\n✅ ¡SISTEMA OPERATIVO! Robot en modo patrulla.")
    ultimo_envio_ia = 0.0

    try:
        while True:
            frame = camara_stream.read()
            if frame is None:
                continue

            # ====================================================
            # 🧠 CEREBRO DEL ROBOT: JERARQUÍA DE DECISIONES
            # ====================================================
            d_cen = sensor_cen.distance_cm()
            d_der = sensor_der.distance_cm()
            d_izq = sensor_izq.distance_cm()

            # 🛑 PRIORIDAD 1: SUPERVIVENCIA (Evasión de colisiones)
            if d_cen < 15.0: # Emergencia absoluta
                print(f"¡PELIGRO! Muro inminente a {d_cen:.1f} cm -> FRENANDO / RETROCEDIENDO")
                fijar_velocidades(-VEL_BASE, -VEL_BASE)
                time.sleep(0.5)
                girar_izquierda(VEL_BASE)
                time.sleep(0.5)
                continue

            elif d_cen < DIST_FRENTE_MIN:
                print(f"Obstáculo al frente ({d_cen:.1f} cm) -> Girando IZQUIERDA")
                girar_izquierda(VEL_BASE)
            
            else:
                # 🐕 PRIORIDAD 2: RASTREO VISUAL LOCAL
                blob = cv2.dnn.blobFromImage(cv2.resize(frame, (300, 300)), 0.007843, (300, 300), 127.5)
                net.setInput(blob)
                detecciones = net.forward()
                
                mascota_detectada = False
                centro_x = 0

                for i in np.arange(0, detecciones.shape[2]):
                    confianza = detecciones[0, 0, i, 2]
                    if confianza > 0.6: # 60% de seguridad
                        clase_id = int(detecciones[0, 0, i, 1])
                        # Clase 8 es 'Gato', Clase 12 es 'Perro'
                        if clase_id == 8 or clase_id == 12:
                            mascota_detectada = True
                            caja = detecciones[0, 0, i, 3:7] * np.array([ANCHO, ALTO, ANCHO, ALTO])
                            (startX, startY, endX, endY) = caja.astype("int")
                            centro_x = (startX + endX) / 2
                            break # Solo seguimos al primero que veamos

                if mascota_detectada:
                    # Seguimiento basado en la posición de la mascota en pantalla
                    if centro_x < 250:
                        print("👀 Mascota a la IZQUIERDA -> Corrigiendo rumbo.")
                        fijar_velocidades(0.4, VEL_BASE)
                    elif centro_x > 390:
                        print("👀 Mascota a la DERECHA -> Corrigiendo rumbo.")
                        fijar_velocidades(VEL_BASE, 0.4)
                    else:
                        print("🎯 Mascota EN EL CENTRO -> ¡Avanzando!")
                        avanzar(VEL_BASE)
                
                else:
                    # 🧭 PRIORIDAD 3: PATRULLAJE (Wall-Following)
                    if d_izq < DIST_PARED_MIN:
                        fijar_velocidades(VEL_BASE, 0.5)  
                    elif d_der < DIST_PARED_MIN:
                        fijar_velocidades(0.5, VEL_BASE) 
                    elif d_der > DIST_PARED_MAX:
                        fijar_velocidades(VEL_BASE, 0.5) 
                    else:
                        avanzar(VEL_BASE)

            # ====================================================
            # ☁️ TELEMETRÍA: ENVÍO A GOOGLE CLOUD
            # ====================================================
            tiempo_actual = time.time()
            if tiempo_actual - ultimo_envio_ia >= 1.0: # 1 fotograma por segundo a la App/Nube
                _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
                try:
                    publisher.publish(topic_path, buffer.tobytes())
                    ultimo_envio_ia = tiempo_actual
                except Exception:
                    pass

            time.sleep(0.05) # Pequeño respiro para la CPU local

    except KeyboardInterrupt:
        print("\n🛑 Apagando el sistema...")
    finally:
        detener()
        camara_stream.stop()
        servo.stop()
        GPIO.cleanup()
        print("¡Robot aparcado con éxito!")

if __name__ == "__main__":
    main()