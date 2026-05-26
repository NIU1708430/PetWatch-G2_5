# heuristics.py

def analizar_postura(points_norm):
    """
    Recibe los 17 puntos normalizados [x, y] de la ResNet (AP-10K).
    3: Cuello, 4: Base de la cola
    7 y 10: Patas delanteras
    13 y 16: Patas traseras
    """
    if points_norm is None or len(points_norm) < 17:
        return "DESCONOCIDA"

    # Extraemos las alturas (eje Y)
    y_cuello = points_norm[3][1]
    y_cola = points_norm[4][1]
    
    y_patas_delanteras = (points_norm[7][1] + points_norm[10][1]) / 2
    y_patas_traseras = (points_norm[13][1] + points_norm[16][1]) / 2
    
    # Calculamos distancias absolutas
    dist_delantera = abs(y_patas_delanteras - y_cuello)
    dist_trasera = abs(y_patas_traseras - y_cola)
    
    umbral_tumbado = 0.15 
    
    # Clasificación basada en reglas
    if dist_delantera < umbral_tumbado and dist_trasera < umbral_tumbado:
        return "TUMBADO"
    elif dist_delantera > umbral_tumbado and dist_trasera < umbral_tumbado:
        return "SENTADO"
    elif dist_delantera > umbral_tumbado and dist_trasera > umbral_tumbado:
        return "DE PIE"
    else:
        return "DESCONOCIDA"