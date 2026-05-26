import base64
import json
import requests

URL_LOCAL = "http://localhost:8080"
RUTA_FOTO = "perro_prueba.jpg"

def simular_envio():
    try:
        # 1. Leer la foto del disco duro
        with open(RUTA_FOTO, "rb") as image_file:
            foto_bytes = image_file.read()
            
        # 2. Convertir la foto a texto Base64 
        foto_base64 = base64.b64encode(foto_bytes).decode("utf-8")
        
        # 3. Crear el "disfraz" de Google Pub/Sub
        payload_pubsub = {
            "message": {
                "data": foto_base64,
                "messageId": "simulacion_local_001",
                "publishTime": "2026-05-26T18:00:00.000Z"
            }
        }
        
        # 4. Disparar el mensaje hacia nuestro servidor local
        print(f"📡 Enviando '{RUTA_FOTO}' al servidor local...")
        respuesta = requests.post(URL_LOCAL, json=payload_pubsub)
        
        print(f"Respuesta del servidor: HTTP {respuesta.status_code}")
        
    except FileNotFoundError:
        print(f"Error: No se encuentra la foto '{RUTA_FOTO}' en esta carpeta.")
    except Exception as e:
        print(f"Error al enviar: {e}")

if __name__ == "__main__":
    simular_envio()