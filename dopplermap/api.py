import frappe
import requests
import json
import time

# =====================================================================
# 1. CONEXIÓN SEGURA CON GOOGLE GEMINI (BACKEND)
# =====================================================================

@frappe.whitelist()
def generar_reporte_gemini(prompt_text):
    try:
        config = frappe.get_doc("Configuracion Gemini")
        api_key = config.api_key
        if not api_key:
            frappe.throw("Error: No hay API Key configurada en 'Configuracion Gemini'.")

        # Parámetros
        modelo_principal = config.modelo_predeterminado or "gemini-2.5-flash"
        # Opcional: modelo alternativo si el principal falla por cuota
        modelo_fallback = "gemini-1.5-flash"  # puedes configurarlo en el DocType si quieres

        # Temperatura
        try:
            temperatura = float(config.temperatura) if config.temperatura else 0.3
        except (TypeError, ValueError):
            temperatura = 0.3
        temperatura = max(0.0, min(temperatura, 2.0))

        # Construir payload base
        base_payload = {
            "contents": [{"parts": [{"text": prompt_text}]}],
            "systemInstruction": {
                "parts": [{
                    "text": "Actúa como un ecografista vascular senior. Tu único propósito es redactar un informe médico clínico, estructurado y preciso a partir de una matriz de datos JSON."
                }]
            },
            "generationConfig": {
                "temperature": temperatura
            }
        }

        # Lista de modelos a probar (principal y luego fallback)
        modelos_a_probar = [modelo_principal]
        if modelo_fallback and modelo_fallback != modelo_principal:
            modelos_a_probar.append(modelo_fallback)

        # Configuración de reintentos: máximo 3 por modelo, con backoff exponencial
        max_retries = 3
        base_delay = 1  # segundos

        for modelo in modelos_a_probar:
            for intento in range(max_retries):
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={api_key}"
                    frappe.log_error(f"Intentando modelo {modelo}, intento {intento+1}/{max_retries}", "Gemini Retry")
                    
                    headers = {"Content-Type": "application/json"}
                    response = requests.post(url, headers=headers, json=base_payload, timeout=30)

                    if response.status_code == 200:
                        data = response.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts:
                                texto = parts[0].get("text", "")
                                if texto:
                                    frappe.log_error(f"Respuesta exitosa con modelo {modelo}", "Gemini Info")
                                    return texto
                    elif response.status_code == 429:
                        # Quota excedida: pasamos al siguiente modelo sin reintentar
                        frappe.log_error(f"Quota excedida para modelo {modelo}, cambiando al siguiente", "Gemini Quota")
                        break  # sale del bucle de reintentos y prueba el siguiente modelo
                    elif response.status_code in [500, 502, 503, 504]:
                        # Errores transitorios del servidor: reintentar
                        wait = base_delay * (2 ** intento)
                        frappe.log_error(f"Error {response.status_code} en modelo {modelo}, reintentando en {wait}s", "Gemini Retry")
                        time.sleep(wait)
                        continue
                    else:
                        # Otros errores (400, 401, etc.) no reintentamos, pero registramos
                        error_msg = f"Error {response.status_code} en modelo {modelo}: {response.text}"
                        frappe.log_error(error_msg, "Gemini Error")
                        # Si es el último modelo, lanzamos error
                        if modelo == modelos_a_probar[-1] and intento == max_retries-1:
                            frappe.throw(f"Google Gemini respondió con error: {error_msg}")
                        else:
                            break  # prueba siguiente modelo
                except requests.exceptions.RequestException as e:
                    frappe.log_error(f"Excepción de red: {str(e)}", "Gemini Request Error")
                    wait = base_delay * (2 ** intento)
                    time.sleep(wait)
                    continue
                except Exception as e:
                    frappe.log_error(f"Error inesperado: {str(e)}", "Gemini Unexpected")
                    if intento == max_retries-1:
                        frappe.throw(f"Error interno: {str(e)}")
                    time.sleep(base_delay * (2 ** intento))
                    continue

        # Si agotamos todos los modelos y reintentos
        frappe.throw("No se pudo obtener respuesta de Gemini después de múltiples intentos y modelos alternativos.")

    except Exception as e:
        frappe.log_error(message=frappe.get_traceback(), title="Error en API Gemini")
        frappe.throw(f"Error interno: {str(e)}")


# =====================================================================
# 2. GUARDADO DE DATOS EN EL DOCTYPE 'VASCULAR ENCOUNTER - ECO DOPPLER'
# =====================================================================
@frappe.whitelist()
def guardar_doppler_frontend(encounter_id, sistema, reporte_ia, matriz_datos):
    """
    Guarda o actualiza un registro de 'Vascular Encounter - Eco Doppler'
    vinculado al encuentro clínico (Vascular Encounter) dado por encounter_id.
    """
    # --- LOG 1: Función iniciada
    frappe.log_error(f"Inicio guardar_doppler_frontend; encounter_id={encounter_id}, sistema={sistema}", "Doppler Log")

    if not encounter_id:
        frappe.log_error("Falta encounter_id", "Doppler Log")
        frappe.throw("No se proporcionó un ID de Encuentro.")

    # Verificar que el Vascular Encounter padre exista
    if not frappe.db.exists("Vascular Encounter", encounter_id):
        frappe.log_error(f"No existe Vascular Encounter con ID {encounter_id}", "Doppler Log")
        frappe.throw(f"No se encontró el Vascular Encounter con ID {encounter_id}")

    try:
        # --- LOG 2: Antes de buscar/crear el eco doppler
        frappe.log_error(f"Buscando Vascular Encounter - Eco Doppler con parent_encounter={encounter_id}", "Doppler Log")
        filters = {"parent_encounter": encounter_id}
        existing = frappe.db.get_value("Vascular Encounter - Eco Doppler", filters, "name")
        frappe.log_error(f"Resultado búsqueda: {existing}", "Doppler Log")

        if existing:
            doc = frappe.get_doc("Vascular Encounter - Eco Doppler", existing)
            frappe.log_error(f"Documento existente cargado: {doc.name}", "Doppler Log")
        else:
            # Crear nuevo registro
            doc = frappe.get_doc({
                "doctype": "Vascular Encounter - Eco Doppler",
                "parent_encounter": encounter_id,
                "sistema_evaluado": sistema,
                "reporte_ia": reporte_ia,
            })
            doc.insert(ignore_permissions=True)
            frappe.log_error(f"Nuevo documento creado: {doc.name}", "Doppler Log")

        # Actualizar campos principales
        doc.sistema_evaluado = sistema
        doc.reporte_ia = reporte_ia
        if doc.meta.get_field("matriz_json"):
            doc.matriz_json = matriz_datos
            frappe.log_error("Campo matriz_json actualizado", "Doppler Log")

        # Limpiar child table
        doc.set("detalles_segmentos", [])
        frappe.log_error("Child table limpiada", "Doppler Log")

        # Parsear matriz_datos
        try:
            datos = json.loads(matriz_datos) if isinstance(matriz_datos, str) else matriz_datos
            frappe.log_error(f"Matriz parseada correctamente. Keys: {list(datos.keys())}", "Doppler Log")
        except json.JSONDecodeError as e:
            frappe.log_error(f"Error parseando JSON: {str(e)}", "Doppler Log")
            frappe.throw("La matriz de datos no es un JSON válido.")

        # Recorrer lateralidades y segmentos
        total_filas = 0
        for lateralidad, segmentos in datos.items():
            frappe.log_error(f"Procesando lateralidad: {lateralidad}", "Doppler Log")
            if lateralidad not in ["DERECHA", "IZQUIERDA"]:
                frappe.log_error(f"Lateralidad ignorada (no válida): {lateralidad}", "Doppler Log")
                continue
            for nombre_segmento, valores in segmentos.items():
                total_filas += 1
                frappe.log_error(f"Segmento: {nombre_segmento}, valores: {valores}", "Doppler Log")
                # ... (el resto de la lógica de extracción es la misma que tenías)
                # Extraer diametro, reflujo, psv, hallazgos...
                diametro = valores.get('diametro')
                if diametro is not None:
                    try:
                        diametro = float(diametro)
                    except:
                        diametro = None

                reflujo = valores.get('reflujo')
                if reflujo is not None:
                    try:
                        reflujo = int(reflujo)
                    except:
                        reflujo = None

                psv = valores.get('psv')
                if psv is not None:
                    try:
                        psv = float(psv)
                    except:
                        psv = None

                hallazgos = valores.get('hallazgos')
                if not hallazgos and isinstance(valores, dict):
                    parts = []
                    if valores.get('color'):
                        parts.append(str(valores['color']))
                    if valores.get('pared'):
                        p = valores['pared']
                        if isinstance(p, list):
                            parts.extend([str(x) for x in p])
                        else:
                            parts.append(str(p))
                    if valores.get('focal'):
                        f = valores['focal']
                        if isinstance(f, list):
                            parts.extend([str(x) for x in f])
                        else:
                            parts.append(str(f))
                    if valores.get('interventions'):
                        inv = valores['interventions']
                        if isinstance(inv, list):
                            parts.extend([str(x) for x in inv])
                        else:
                            parts.append(str(inv))
                    hallazgos = ", ".join(parts) if parts else None

                if hallazgos and len(hallazgos) > 140:
                    hallazgos = hallazgos[:140]

                doc.append('detalles_segmentos', {
                    'lateralidad': lateralidad,
                    'segmento': nombre_segmento,
                    'diametro': diametro,
                    'reflujo': reflujo,
                    'psv': psv,
                    'hallazgos': hallazgos
                })
                frappe.log_error(f"Fila añadida para {nombre_segmento}", "Doppler Log")

        frappe.log_error(f"Total de filas procesadas: {total_filas}", "Doppler Log")

        # Guardar documento
        doc.save(ignore_permissions=False)
        frappe.db.commit()
        frappe.log_error(f"Documento {doc.name} guardado exitosamente", "Doppler Log")

        return doc.name

    except Exception as e:
        frappe.log_error(f"EXCEPCIÓN CAPTURADA: {frappe.get_traceback()}", "Doppler Log")
        frappe.throw(f"Error al guardar en la Historia Clínica: {str(e)}")