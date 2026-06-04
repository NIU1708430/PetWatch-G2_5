import base64
import cv2
import numpy as np
import functions_framework
from google.cloud import firestore
import firebase_admin
from firebase_admin import credentials, messaging
from datetime import datetime, timezone, timedelta

# Inicializamos Firebase Admin 
if not firebase_admin._apps:
    firebase_admin.initialize_app()

db = firestore.Client(project="petwatch-sm", database="petwatch-db")

@functions_framework.cloud_event
def procesar_ia_mascotas(cloud_event):
    """
    Se ejecuta cada vez que el PC manda un fotograma.
    Guarda SIEMPRE la imagen en Firestore para que la web tenga vídeo continuo.
    Envía notificaciones masivas si la mascota es detectada (con control de spam).
    """
    from yolo_detector import detectar_animal
    from pose_estimator import estimar_esqueleto
    
    # 1. LEER MENSAJE
    pubsub_message = cloud_event.data.get("message")
    if not pubsub_message or "data" not in pubsub_message:
        return

    # 2. DECODIFICAR IMAGEN GENERAL
    img_bytes = base64.b64decode(pubsub_message["data"])
    img_arr = np.frombuffer(img_bytes, dtype=np.uint8)
    frame_completo = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)

    if frame_completo is None:
        return

    # VALORES POR DEFECTO
    tipo_animal = "Ninguno"
    accion = "Monitoreando..."
    imagen_para_enviar = frame_completo 
    
    # 3. INTENTAR DETECTAR MASCOTA
    resultado_yolo = detectar_animal(frame_completo) 

    # SI SÍ HAY UN PERRO/GATO: Hacemos el zoom (recorte) y la postura
    if resultado_yolo is not None:
        caja_animal, tipo_animal = resultado_yolo
        x1, y1, x2, y2 = caja_animal
        
        # Recortamos para enfocar a la mascota
        recorte_mascota = frame_completo[y1:y2, x1:x2]
        imagen_para_enviar = recorte_mascota 

        # Esqueleto y postura
        puntos_clave = estimar_esqueleto(recorte_mascota)
        if puntos_clave is not None:
            from heuristics import analizar_postura
            accion = analizar_postura(puntos_clave)
    
    # Convertimos la imagen elegida (el plano general o el recorte) a texto Base64
    _, buffer = cv2.imencode('.jpg', imagen_para_enviar)
    img_base64 = base64.b64encode(buffer).decode('utf-8')
  
    # Subimos el documento actualizado
    datos_mascota = {
        "animal": tipo_animal, 
        "postura": accion,
        "foto_b64": img_base64,
        "fecha_hora": firestore.SERVER_TIMESTAMP
    }

    try:
        db.collection("historial_mascotas").add(datos_mascota)
        print("¡Fotograma enviado a la web con éxito!")
    except Exception as e:
        print(f"Error al guardar: {e}")

    # 4. Avisa con cualquier postura  si hay un animal real
    if tipo_animal != "Ninguno":
        try:
            doc_ref = db.collection("estado_sistema").document("control_alertas")
            doc = doc_ref.get()
            enviar_mensaje = True
            
            if doc.exists:
                datos_alerta = doc.to_dict()
                ultima_alerta = datos_alerta.get("ultima_alerta")
                
                if ultima_alerta:
                    ahora = datetime.now(timezone.utc)
                    diferencia = ahora - ultima_alerta
                    
                    # Comprobamos si han pasado menos de 3 minutos (180 segundos)
                    if diferencia < timedelta(minutes=3):
                        enviar_mensaje = False
                        segundos_restantes = 180 - diferencia.seconds
                        print(f"Spam evitado cinematográficamente. Faltan {segundos_restantes} segundos para poder enviar otra alerta.")

            # Si el cooldown ha vencido o es la primera alerta, disparamos la ráfaga
            if enviar_mensaje:
                # 0. Guardar en la galeria la foto de la notificacion
                try:
                    db.collection("alertas_guardadas").add({
                        "animal": tipo_animal,
                        "postura": accion,
                        "foto_b64": img_base64,
                        "fecha_hora": firestore.SERVER_TIMESTAMP
                    })
                    print("¡Foto infraganti guardada en la galería permanente!")
                except Exception as save_gallery_error:
                    print(f"Error al guardar en galería: {save_gallery_error}")

                # 1. Recuperamos de forma masiva todos los tokens registrados por Flutter
                suscripciones = db.collection("usuarios_suscritos").stream()
                lista_tokens = []
                
                for doc in suscripciones:
                    datos = doc.to_dict()
                    if "token" in datos:
                        lista_tokens.append(datos["token"])
                
                # 2. Si hay dispositivos apuntados en el buzón, disparamos la ráfaga
                if len(lista_tokens) > 0:
                    mensaje_masivo = messaging.MulticastMessage(
                        notification=messaging.Notification(
                            title="¡Aviso de PetWatch!",
                            body=f"Tu {tipo_animal} está: {accion}"
                        ),
                        tokens=lista_tokens,
                    )

                    # Envía el mensaje de golpe a toda la lista de tokens recopilada
                    response = messaging.send_each_for_multicast(mensaje_masivo)
                    print(f"¡Notificación masiva enviada con éxito a {response.success_count} dispositivos!")
                    
                    # Guardamos el momento exacto de este envío para iniciar el bloqueo temporal
                    doc_ref.set({"ultima_alerta": firestore.SERVER_TIMESTAMP})
                else:
                    print("Se detectó una alerta, pero no hay ningún dispositivo registrado en 'usuarios_suscritos'.")

        except Exception as fcm_error:
            print(f"Error en el proceso de notificación masiva FCM: {fcm_error}")