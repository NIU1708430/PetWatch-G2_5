def analizar_postura(points_norm):
    # Capa de clasificacion determinista (Expert System) aplicada sobre el tensor de Keypoints.
    # Nodos relevantes de AP-10K: Cuello (3), Cola (4), Patas delanteras (7,10), Patas traseras (13,16)
    
    if points_norm is None or len(points_norm) < 17:
        return "DESCONOCIDA"

    # Extraccion de la componente Y (altura relativa) de los vectores de articulacion
    y_cuello = points_norm[3][1]
    y_cola = points_norm[4][1]
    
    # Suavizado calculando la elevacion media entre pares de patas
    y_patas_delanteras = (points_norm[7][1] + points_norm[10][1]) / 2
    y_patas_traseras = (points_norm[13][1] + points_norm[16][1]) / 2
    
    # Diferencia biomecanica absoluta (distancia vertical en la imagen)
    dist_delantera = abs(y_patas_delanteras - y_cuello)
    dist_trasera = abs(y_patas_traseras - y_cola)
    
    # Umbral de sensibilidad para la clasificacion
    umbral_tumbado = 0.15 
    
    # Arbol de decision heuristica
    if dist_delantera < umbral_tumbado and dist_trasera < umbral_tumbado:
        # Ambos ejes corporales colapsados contra el suelo
        return "TUMBADO"
    elif dist_delantera > umbral_tumbado and dist_trasera < umbral_tumbado:
        # Tronco erguido, cadera en contacto con la superficie
        return "SENTADO"
    elif dist_delantera > umbral_tumbado and dist_trasera > umbral_tumbado:
        # Maxima extension en ambos ejes vectoriales
        return "DE PIE"
    else:
        return "DESCONOCIDA"