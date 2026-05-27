import time
import cv2  # Usaremos cv2 solo para comprimir el fotograma a JPG en memoria
from google.cloud import pubsub_v1
from picamera2 import Picamera2


# ================= CONFIGURACIÓN =================
PROJECT_ID = "petwatch-sm"
TOPIC_ID = "petwatch-video-stream"
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


    # 2. Inicialización de Picamera2
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


    try:
        while True:
            # Capturar un fotograma directamente en memoria como una matriz RGB
            frame_rgb = picam2.capture_array("main")


            # Convertir la matriz de RGB a BGR (que es lo que entiende OpenCV)
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)


            # Comprimir la imagen a formato JPG para que viaje rápido por internet
            _, buffer = cv2.imencode('.jpg', frame_bgr)
            img_bytes = buffer.tobytes()


            try:
                # Enviar los bytes comprimidos directamente a Google Cloud Pub/Sub
                future = publisher.publish(topic_path, img_bytes)
                print(f"[{time.strftime('%H:%M:%S')}] Fotograma enviado con éxito. ID: {future.result()}")
            except Exception as pub_error:
                print(f"Error al enviar a Pub/Sub: {pub_error}")


            # Enviar 1 fotograma por segundo
            time.sleep(1)


    except KeyboardInterrupt:
        print("\nTransmisión detenida de forma manual desde la terminal.")
    finally:
        # Cerrar la cámara de forma segura
        picam2.stop()
        print("Cámara apagada correctamente. ¡Proyecto cerrado!")


if __name__ == "__main__":
    main()







"""
import time
import io
from google.cloud import pubsub_v1
from picamera2 import Picamera2 # La librería moderna oficial para Raspberry Pi

# ================= CONFIGURACIÓN =================
PROJECT_ID = "petwatch-sm"
TOPIC_ID = "petwatch-video-stream"
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

    # 2. Inicialización de Picamera2
    print("Iniciando Raspberry Pi Camera Module v2 con Picamera2...")
    try:
        picam2 = Picamera2()
        
        # Configuramos la resolución directamente a 640x480 en formato JPEG
        picam2.configure(picam2.create_video_configuration(
            main={"format": "JPEG", "size": (640, 480)}
        ))
        
        picam2.start()
        print("\n[OK] Cámara v2 lista mediante Picamera2 y transmitiendo.")
        print("--> Para detener la transmisión, pulsa Ctrl + C en esta terminal.")
        print("==================================================\n")
    except Exception as cam_error:
        print(f"Error: No se pudo inicializar la cámara con Picamera2. {cam_error}")
        return

    try:
        while True:
            # Capturar un fotograma directamente en memoria como bytes JPEG
            img_bytes = picam2.capture_array("main")

            try:
                # Enviar los bytes directamente a Google Cloud Pub/Sub
                future = publisher.publish(topic_path, img_bytes)
                print(f"[{time.strftime('%H:%M:%S')}] Fotograma enviado con éxito. ID: {future.result()}")
            except Exception as pub_error:
                print(f"Error al enviar a Pub/Sub: {pub_error}")

            # Enviar 1 fotograma por segundo
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nTransmisión detenida de forma manual desde la terminal.")
    finally:
        # Cerrar la cámara de forma segura
        picam2.stop()
        print("Cámara apagada correctamente. ¡Proyecto cerrado!")

if __name__ == "__main__":
    main()





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
    cap = cv2.VideoCapture(-1)  # El 0 activa la cámara integrada de tu ordenador

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
