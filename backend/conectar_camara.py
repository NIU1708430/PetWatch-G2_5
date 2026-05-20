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
                # Enviar los bytes directamente (Pub/Sub lo envuelve en Base64 por nosotros)
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