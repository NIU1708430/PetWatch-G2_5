import base64
import cv2
import numpy as np
import functions_framework
from google.cloud import firestore
from google.cloud import vision
import firebase_admin
from firebase_admin import credentials, messaging
from datetime import datetime, timezone, timedelta

# Inicializacion global para reutilizar conexiones entre invocaciones (mitigacion de Cold Start)
if not firebase_admin._apps:
    firebase_admin.initialize_app()

db = firestore.Client(project="petwatch-sm", database="petwatch-db")
vision_client = vision.ImageAnnotatorClient()

@functions_framework.cloud_event
def procesar_ia_mascotas(cloud_event):
    from pose_estimator import estimar_esqueleto
    
    # 1. Ingesta de Telemetria Visual
    pubsub_message = cloud_event.data.get("message")
    if not pubsub_message or "data" not in pubsub_message:
        return

    img_bytes = base64.b64decode(pubsub_message["data"])
    img_arr = np.frombuffer(img_bytes, dtype=np.uint8)
    frame_completo = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)

    if frame_completo is None:
        return

    alto_img, ancho_img, _ = frame_completo.shape

    # Estado inicial por defecto
    tipo_animal = "Ninguno"
    accion = "Monitoreando..."
    raza_detectada = ""
    imagen_para_enviar = frame_completo 
    
    # 2. FASE 1: Inferencia Semantica General (Google Cloud Vision)
    vision_image = vision.Image(content=img_bytes)
    
    respuesta_etiquetas = vision_client.label_detection(image=vision_image)
    respuesta_objetos = vision_client.object_localization(image=vision_image)
    
    # Analisis semantico de etiquetas para inferir la raza especifica
    for etiqueta in respuesta_etiquetas.label_annotations:
        desc = etiqueta.description.lower()
        palabras = desc.split()
        
        # Filtramos categorias genericas para obtener una descripcion mas rica en UI
        if "dog" in palabras or "cat" in palabras or "breed" in palabras or "retriever" in palabras:
            raza_detectada = etiqueta.description
            break

    # Deteccion espacial de la Bounding Box
    for objeto in respuesta_objetos.localized_object_annotations:
        if objeto.name.lower() in ["dog", "cat"]:
            tipo_animal = objeto.name
            
            # Desnormalizamos las coordenadas relativas de Vision API a pixeles absolutos
            vertices = objeto.bounding_poly.normalized_vertices
            x1 = int(vertices[0].x * ancho_img)
            y1 = int(vertices[0].y * alto_img)
            x2 = int(vertices[2].x * ancho_img)
            y2 = int(vertices[2].y * alto_img)
            
            # 3. FASE 2: Inferencia de Postura (ResNet-50 Custom AP-10K)
            # Aislamos la region de interes (ROI) para no pasar ruido de fondo al modelo secundario
            recorte_mascota = frame_completo[y1:y2, x1:x2]

            puntos_clave = estimar_esqueleto(recorte_mascota)
            if puntos_clave is not None:
                from heuristics import analizar_postura
                # Capa euristica que clasifica el estado biomecanico en funcion del tensor
                accion = analizar_postura(puntos_clave)
                
            # Renderizado de metadatos en el buffer original
            cv2.rectangle(frame_completo, (x1, y1), (x2, y2), (0, 255, 0), 2)
            
            texto_pantalla = f"{raza_detectada.upper() if raza_detectada else tipo_animal.upper()} - {accion}"
            cv2.putText(frame_completo, texto_pantalla, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            
            # Procesamiento de target unico: optimizamos coste computacional y evitamos cajas sobrepuestas
            break
            
    # 4. Sincronizacion de estado local hacia Firebase
    _, buffer = cv2.imencode('.jpg', frame_completo)
    img_base64 = base64.b64encode(buffer).decode('utf-8')
  
    datos_mascota = {
        "animal": tipo_animal, 
        "raza": raza_detectada,
        "postura": accion,
        "foto_b64": img_base64,
        "fecha_hora": firestore.SERVER_TIMESTAMP
    }

    try:
        # Volcado de la telemetria procesada para consumo en tiempo real del frontend
        db.collection("historial_mascotas").add(datos_mascota)
        print("Sincronizacion de metadatos completada.")
    except Exception as e:
        print(f"Error de persistencia: {e}")

    # 5. Sistema de notificaciones asincronas Push
    if tipo_animal != "Ninguno":
        try:
            # Mecanismo de throttling (Prevencion de Spam)
            doc_ref = db.collection("estado_sistema").document("control_alertas")
            doc = doc_ref.get()
            enviar_mensaje = True
            
            if doc.exists:
                datos_alerta = doc.to_dict()
                ultima_alerta = datos_alerta.get("ultima_alerta")
                
                if ultima_alerta:
                    ahora = datetime.now(timezone.utc)
                    diferencia = ahora - ultima_alerta
                    
                    # Ventana de enfriamiento de 3 minutos para no saturar al usuario
                    if diferencia < timedelta(minutes=3):
                        enviar_mensaje = False
                        segundos_restantes = 180 - diferencia.seconds
                        print(f"Alerta descartada por rate limiting. Reintento en {segundos_restantes}s.")

            if enviar_mensaje:
                try:
                    db.collection("alertas_guardadas").add({
                        "animal": tipo_animal,
                        "raza": raza_detectada,
                        "postura": accion,
                        "foto_b64": img_base64,
                        "fecha_hora": firestore.SERVER_TIMESTAMP
                    })
                except Exception as save_gallery_error:
                    print(f"Fallo de registro en log persistente: {save_gallery_error}")

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
                            title="Aviso de seguridad interactiva",
                            body=f"Tu {nombre_notificacion} esta: {accion}"
                        ),
                        tokens=lista_tokens,
                    )

                    # Envio multicast a todos los clientes suscritos a la arquitectura IoT
                    response = messaging.send_each_for_multicast(mensaje_masivo)
                    print(f"Push notification enviada a {response.success_count} clientes.")
                    
                    # Reinicio atómico del timer de cooldown
                    doc_ref.set({"ultima_alerta": firestore.SERVER_TIMESTAMP})
                else:
                    print("Broadcast abortado: Tabla de tokens FCM vacia.")

        except Exception as fcm_error:
            print(f"Fallo critico en modulo FCM: {fcm_error}")