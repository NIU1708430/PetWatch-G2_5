import time
import cv2  # Usaremos cv2 solo para comprimir el fotograma a JPG en memoria
import subprocess
from google.cloud import pubsub_v1
from picamera2 import Picamera2


# ================= CONFIGURACIÓN =================
PROJECT_ID = "petwatch-sm"
TOPIC_ID = "petwatch-video-stream"
RTSP_URL = "rtsp://localhost:8554/mascota"
ANCHO = 640
ALTO = 480
FPS = 25
# =================================================


def main():
    print("==================================================")
    print("      PETWATCH CLOUD - TRANSMISIÓN EDGE            ")
    print("==================================================")


    # 1. Conexión con Google Cloud Pub/Sub
    print("Conectando con Google Cloud Pub/Sub...")
    try:
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)
        print("-> Conexión establecida correctamente.")
    except Exception as e:
        print(f"Error al conectar con Pub/Sub: {e}")
        return

    # 2. Configurar FFmpeg
    # Mezcla el audio del micrófono físico con los fotogramas que le mande Python
    print("Iniciando codificador multimedia (Vídeo + Audio)...")
    ffmpeg_cmd = [
        'ffmpeg', '-y',

        # Esto es para audio, cuando tengamos el micro funcionando se tiene que descomentar
        #'-f', 'alsa', '-i', 'default',       # Captura el audio del micrófono de la Pi
        
        '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-pix_fmt', 'bgr24',                 # Formato nativo de OpenCV
        '-s', f'{ANCHO}x{ALTO}', '-r', str(FPS),
        '-i', '-',                           # Recibe los fotogramas por la tubería (stdin)
        '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency',

        # Cuando tengamos micro hay que eliminar el -an y descomentar lo de debajo
        '-an',
        #'-c:a', 'aac', '-b:a', '64k',

        '-f', 'rtsp', RTSP_URL               # Lo inyecta en MediaMTX
    ]
    try:
        proceso_stream = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)
        print("-> Codificador listo y conectado a MediaMTX.")
    except Exception as e:
        print(f"Error al iniciar FFmpeg (¿Está MediaMTX corriendo?): {e}")
        return

    # 3. Inicialización de Picamera2
    print("Iniciando Raspberry Pi Camera Module v2 con Picamera2...")
    try:
        picam2 = Picamera2()
       
        # Configuramos la cámara en formato RGB estándar a 640x480
        picam2.configure(picam2.create_video_configuration(
            main={"format": "RGB888", "size": (640, 480)}
        ))
       
        picam2.start()
        print("\n[OK] Cámara v2 lista mediante Picamera2 y transmitiendo.")
        print("--> Para detener la transmisión, pulsa Ctrl + C en esta terminal.")
        print("==================================================\n")
    except Exception as cam_error:
        print(f"Error: No se pudo inicializar la cámara con Picamera2. {cam_error}")
        return

    ultimo_envio_ia = 0.0

    try:
        while True:
            # Capturar un fotograma directamente en memoria como una matriz RGB
            frame_rgb = picam2.capture_array("main")


            # Convertir la matriz de RGB a BGR (que es lo que entiende OpenCV)
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)


            try:
                # Enviar los pixeles puros a FFmpeg para el streaming
                proceso_stream.stdin.write(frame_bgr.tobytes())
            except Exception as stream_error:
                print(f"Error en el stream en directo: {stream_error}")


            tiempo_actual = time.time()
            if tiempo_actual - ultimo_envio_ia >= 0.2:
                # Comprimir la imagen a formato JPG para que viaje rápido por internet
                _, buffer = cv2.imencode('.jpg', frame_bgr)
                img_bytes = buffer.tobytes()


                try:
                    # Enviar los bytes comprimidos directamente a Google Cloud Pub/Sub
                    future = publisher.publish(topic_path, img_bytes)
                    print(f"[{time.strftime('%H:%M:%S')}] Fotograma enviado con éxito. ID: {future.result()}")
                    ultimo_envio_ia = tiempo_actual
                except Exception as pub_error:
                    print(f"Error al enviar a Pub/Sub: {pub_error}")


            # tiempo entre fotograma y fotograma
            time.sleep(0.01)


    except KeyboardInterrupt:
        print("\nTransmisión detenida de forma manual desde la terminal.")
    finally:
        # Cerrar la cámara de forma segura
        picam2.stop()
        if proceso_stream:
            proceso_stream.stdin.close()
            proceso_stream.wait()
        print("Cámara apagada correctamente. ¡Proyecto cerrado!")


if __name__ == "__main__":
    main()







"""
import cv2
import time
import base64
from google.cloud import pubsub_v1

# ================= CONFIGURACIÓN =================
PROJECT_ID = "petwatch-sm" 
TOPIC_ID = "petwatch-video-stream"
# =================================================

def main():
    print("==================================================")
    print("     PETWATCH CLOUD - TRANSMISIÓN EDGE            ")
    print("==================================================")
    
    # 1. Conexión con Google Cloud Pub/Sub usando tus credenciales locales (ADC)
    print("Conectando con Google Cloud Pub/Sub...")
    try:
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)
        print("-> Conexión establecida correctamente.")
    except Exception as e:
        print(f"Error al conectar con Pub/Sub: {e}")
        return

    # 2. Inicialización de la cámara con OpenCV
    print("Iniciando cámara web...")
    cap = cv2.VideoCapture(0)  # El 0 activa la cámara integrada de tu ordenador

    if not cap.isOpened():
        print("Error: No se ha detectado ninguna cámara activa.")
        return

    print("\n[OK] Cámara transmitiendo en directo.")
    print("--> Pulsa la tecla 'q' dentro de la ventana de vídeo para salir.")
    print("==================================================\n")

    try:
        while True:
            # Capturar fotograma a fotograma
            ret, frame = cap.read()
            if not ret:
                print("Error al leer el fotograma de la cámara.")
                break

            # Mostrar el vídeo en una ventana local (para que veas que funciona)
            cv2.imshow('PetWatch - Vista Previa de la Mascota', frame)

            # Optimización: Reducimos resolución para que viaje rápido por internet
            frame_resized = cv2.resize(frame, (640, 480))
            
            # Codificar la imagen a formato JPG
            _, buffer = cv2.imencode('.jpg', frame_resized)
            
            try:
                # Enviar los bytes directamente 
                future = publisher.publish(topic_path, buffer.tobytes())
                print(f"[{time.strftime('%H:%M:%S')}] Fotograma enviado con éxito. ID: {future.result()}")
            except Exception as pub_error:
                print(f"Error al enviar a Pub/Sub: {pub_error}")

            # Enviar 1 fotograma por segundo para no saturar los créditos del proyecto
            time.sleep(1)

            # Si pulsas la tecla 'q' en el teclado, se cierra todo
            if cv2.waitKey(1) & 0xFF == ord('q'):
                print("Cerrando la transmisión...")
                break

    except KeyboardInterrupt:
        print("\nTransmisión detenida desde la terminal.")
    finally:
        # Liberar la cámara y cerrar las ventanas de OpenCV
        cap.release()
        cv2.destroyAllWindows()
        print("Cámara apagada. ¡Proyecto finalizado con éxito por hoy!")

if __name__ == "__main__":
    main()


"""
