import base64
import cv2
import numpy as np
import functions_framework
from google.cloud import firestore
from google.cloud import vision
import firebase_admin
from firebase_admin import credentials, messaging
from datetime import datetime, timezone, timedelta

# Inicializamos Firebase Admin 
if not firebase_admin._apps:
    firebase_admin.initialize_app()

db = firestore.Client(project="petwatch-sm", database="petwatch-db")
# Inicializamos el cliente de Google Cloud Vision
vision_client = vision.ImageAnnotatorClient()

@functions_framework.cloud_event
def procesar_ia_mascotas(cloud_event):
    """
    Se ejecuta cada vez que el PC/Robot manda un fotograma.
    Usa Cloud Vision API para detección y ResNet local para posturas.
    """
    from pose_estimator import estimar_esqueleto
    
    # 1. LEER MENSAJE DE PUB/SUB
    pubsub_message = cloud_event.data.get("message")
    if not pubsub_message or "data" not in pubsub_message:
        return

    # 2. DECODIFICAR IMAGEN GENERAL
    img_bytes = base64.b64decode(pubsub_message["data"])
    img_arr = np.frombuffer(img_bytes, dtype=np.uint8)
    frame_completo = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)

    if frame_completo is None:
        return

    alto_img, ancho_img, _ = frame_completo.shape

    # VALORES POR DEFECTO
    tipo_animal = "Ninguno"
    accion = "Monitoreando..."
    raza_detectada = ""
    imagen_para_enviar = frame_completo 
    
    # ====================================================================
    # 3. FASE 1: GOOGLE CLOUD VISION API 
    # ====================================================================
    vision_image = vision.Image(content=img_bytes)
    
    # Pedimos etiquetas (para intentar sacar la raza) y objetos (para la caja)
    respuesta_etiquetas = vision_client.label_detection(image=vision_image)
    respuesta_objetos = vision_client.object_localization(image=vision_image)
    
    # Buscamos si hay perros o gatos en las etiquetas para dar más contexto
    for etiqueta in respuesta_etiquetas.label_annotations:
        desc = etiqueta.description.lower()
        palabras = desc.split()
        
        # Ahora comprobamos si la palabra exacta "cat" o "dog" está en la lista
        if "dog" in palabras or "cat" in palabras or "breed" in palabras or "retriever" in palabras:
            raza_detectada = etiqueta.description
            break

    # Buscamos las cajas 7delimitadoras del animal
    for objeto in respuesta_objetos.localized_object_annotations:
        # Aquí Google Vision sí que devuelve el nombre exacto del objeto detectado, no hay riesgo.
        if objeto.name.lower() in ["dog", "cat"]:
            tipo_animal = objeto.name
            
            # Cloud Vision devuelve coordenadas normalizadas (0.0 a 1.0). Las pasamos a píxeles.
            vertices = objeto.bounding_poly.normalized_vertices
            x1 = int(vertices[0].x * ancho_img)
            y1 = int(vertices[0].y * alto_img)
            x2 = int(vertices[2].x * ancho_img)
            y2 = int(vertices[2].y * alto_img)
            
            # ====================================================================
            # 4. FASE 2: IA DE POSTURAS (ResNet AP-10K)
            # ====================================================================
            # Recortamos la mascota para que la red neuronal secundaria la analice
            recorte_mascota = frame_completo[y1:y2, x1:x2]

            puntos_clave = estimar_esqueleto(recorte_mascota)
            if puntos_clave is not None:
                from heuristics import analizar_postura
                accion = analizar_postura(puntos_clave)
                
            # MAGIA VISUAL: Dibujamos el recuadro y el estado en el plano general
            cv2.rectangle(frame_completo, (x1, y1), (x2, y2), (0, 255, 0), 2)
            
            texto_pantalla = f"{raza_detectada.upper() if raza_detectada else tipo_animal.upper()} - {accion}"
            cv2.putText(frame_completo, texto_pantalla, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            
            # Solo procesamos el primer animal detectado para evitar saturación
            break
            
    # ====================================================================
    # 5. GUARDADO EN FIRESTORE
    # ====================================================================
    _, buffer = cv2.imencode('.jpg', frame_completo)
    img_base64 = base64.b64encode(buffer).decode('utf-8')
  
    # Subimos el documento actualizado (añadiendo la raza por si la app quiere usarla)
    datos_mascota = {
        "animal": tipo_animal, 
        "raza": raza_detectada,
        "postura": accion,
        "foto_b64": img_base64,
        "fecha_hora": firestore.SERVER_TIMESTAMP
    }

    try:
        db.collection("historial_mascotas").add(datos_mascota)
        print("¡Fotograma enviado a la web con éxito!")
    except Exception as e:
        print(f"Error al guardar: {e}")

    # ====================================================================
    # 6. ALERTAS PUSH MASIVAS (Control de Spam)
    # ====================================================================
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
                    
                    if diferencia < timedelta(minutes=3):
                        enviar_mensaje = False
                        segundos_restantes = 180 - diferencia.seconds
                        print(f"Spam evitado cinematográficamente. Faltan {segundos_restantes} segundos.")

            if enviar_mensaje:
                try:
                    db.collection("alertas_guardadas").add({
                        "animal": tipo_animal,
                        "raza": raza_detectada,
                        "postura": accion,
                        "foto_b64": img_base64,
                        "fecha_hora": firestore.SERVER_TIMESTAMP
                    })
                    print("¡Foto infraganti guardada en la galería permanente!")
                except Exception as save_gallery_error:
                    print(f"Error al guardar en galería: {save_gallery_error}")

                suscripciones = db.collection("usuarios_suscritos").stream()
                lista_tokens = []
                
                for doc in suscripciones:
                    datos = doc.to_dict()
                    if "token" in datos:
                        lista_tokens.append(datos["token"])
                
                if len(lista_tokens) > 0:
                    nombre_notificacion = raza_detectada if raza_detectada else tipo_animal
                    mensaje_masivo = messaging.MulticastMessage(
                        notification=messaging.Notification(
                            title="¡Aviso de PetWatch!",
                            body=f"Tu {nombre_notificacion} está: {accion}"
                        ),
                        tokens=lista_tokens,
                    )

                    response = messaging.send_each_for_multicast(mensaje_masivo)
                    print(f"¡Notificación masiva enviada con éxito a {response.success_count} dispositivos!")
                    
                    doc_ref.set({"ultima_alerta": firestore.SERVER_TIMESTAMP})
                else:
                    print("Alerta detectada, pero no hay dispositivos en 'usuarios_suscritos'.")

        except Exception as fcm_error:
            print(f"Error en el proceso de notificación masiva FCM: {fcm_error}")



#main.py antic

"""


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
        
        # 1. Recortamos la mascota SOLO para que la red neuronal secundaria (ResNet) la analice
        recorte_mascota = frame_completo[y1:y2, x1:x2]

        # 2. Esqueleto y postura
        puntos_clave = estimar_esqueleto(recorte_mascota)
        if puntos_clave is not None:
            from heuristics import analizar_postura
            accion = analizar_postura(puntos_clave)
            
        # 3. ¡MAGIA VISUAL! Dibujamos el recuadro y el estado en el plano general
        # Color verde (0, 255, 0) y grosor 2
        cv2.rectangle(frame_completo, (x1, y1), (x2, y2), (0, 255, 0), 2)
        
        # Añadimos un texto flotante encima de la caja
        etiqueta = f"{tipo_animal.upper()} - {accion}"
        cv2.putText(frame_completo, etiqueta, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        
        # 4. Aseguramos que la imagen que viaja a la app de Flutter sea la habitación completa
        imagen_para_enviar = frame_completo
    
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

"""