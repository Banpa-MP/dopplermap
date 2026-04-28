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
# 2. GUARDADO DE DATOS EN EL DOCTYPE 'VASCULAR ENCOUNTER'
# =====================================================================
# =====================================================================
# 2. GUARDADO DE DATOS EN EL DOCTYPE 'VASCULAR ENCOUNTER - ECO DOPPLER'
# =====================================================================
@frappe.whitelist()
def guardar_doppler_frontend(encounter_id, sistema, reporte_ia, matriz_datos):
    """
    Guarda o actualiza un registro de 'Vascular Encounter - Eco Doppler'
    vinculado al encuentro clínico (Vascular Encounter) dado por encounter_id.

    Los detalles de cada segmento se almacenan en la child table
    'Vascular Encounter - Eco Doppler Detail'.
    """
    if not encounter_id:
        frappe.throw("No se proporcionó un ID de Encuentro (Vascular Encounter).")

    # Verificar que el Vascular Encounter padre exista
    if not frappe.db.exists("Vascular Encounter", encounter_id):
        frappe.throw(f"No se encontró el Vascular Encounter con ID {encounter_id}")

    try:
        # 1. Buscar si ya existe un registro de Eco Doppler para este encuentro
        filters = {"parent_encounter": encounter_id}
        existing = frappe.db.get_value("Vascular Encounter - Eco Doppler", filters, "name")

        if existing:
            doc = frappe.get_doc("Vascular Encounter - Eco Doppler", existing)
        else:
            # Crear nuevo registro
            doc = frappe.get_doc({
                "doctype": "Vascular Encounter - Eco Doppler",
                "parent_encounter": encounter_id,
                "sistema_evaluado": sistema,
                "reporte_ia": reporte_ia,
            })
            doc.insert(ignore_permissions=True)

        # 2. Actualizar campos principales
        doc.sistema_evaluado = sistema
        doc.reporte_ia = reporte_ia
        # Si tienes el campo matriz_json (opcional, oculto)
        if doc.meta.get_field("matriz_json"):
            doc.matriz_json = matriz_datos

        # 3. Limpiar la child table existente
        # IMPORTANTE: 'detalles_segmentos' es el fieldname del campo de tipo Table
        # que DEFINISTE en el DocType padre 'Vascular Encounter - Eco Doppler'.
        # Ese campo Table tiene su opción 'Options' configurada como
        # 'Vascular Encounter - Eco Doppler Detail'. Por eso al hacer append(),
        # Frappe sabe qué DocType hijo usar.
        doc.set("detalles_segmentos", [])

        # 4. Parsear la matriz de datos
        try:
            datos = json.loads(matriz_datos) if isinstance(matriz_datos, str) else matriz_datos
        except json.JSONDecodeError:
            frappe.throw("La matriz de datos no es un JSON válido.")

        # 5. Recorrer lateralidades y segmentos
        for lateralidad, segmentos in datos.items():
            if lateralidad not in ["DERECHA", "IZQUIERDA"]:
                continue
            for nombre_segmento, valores in segmentos.items():
                # Extraer valores con conversiones seguras
                diametro = valores.get('diametro')
                if diametro is not None:
                    try:
                        diametro = float(diametro)
                    except (TypeError, ValueError):
                        diametro = None

                reflujo = valores.get('reflujo')
                if reflujo is not None:
                    try:
                        reflujo = int(reflujo)
                    except (TypeError, ValueError):
                        reflujo = None

                psv = valores.get('psv')
                if psv is not None:
                    try:
                        psv = float(psv)
                    except (TypeError, ValueError):
                        psv = None

                # Hallazgos: puede venir como string o construirse
                hallazgos = valores.get('hallazgos')
                if not hallazgos and isinstance(valores, dict):
                    parts = []
                    if valores.get('color'):
                        parts.append(valores['color'])
                    if valores.get('pared'):
                        p = valores['pared']
                        if isinstance(p, list):
                            parts.extend(p)
                        else:
                            parts.append(p)
                    if valores.get('focal'):
                        f = valores['focal']
                        if isinstance(f, list):
                            parts.extend(f)
                        else:
                            parts.append(f)
                    if valores.get('interventions'):
                        inv = valores['interventions']
                        if isinstance(inv, list):
                            parts.extend(inv)
                        else:
                            parts.append(inv)
                    hallazgos = ", ".join(parts) if parts else None

                # Truncar hallazgos a 140 caracteres (máximo para tipo Data)
                if hallazgos and len(hallazgos) > 140:
                    hallazgos = hallazgos[:140]

                # Añadir fila a la child table
                # El campo 'detalles_segmentos' apunta al DocType 'Vascular Encounter - Eco Doppler Detail',
                # por lo que los siguientes campos deben coincidir con los fieldnames de ese DocType.
                doc.append('detalles_segmentos', {
                    'lateralidad': lateralidad,
                    'segmento': nombre_segmento,
                    'diametro': diametro,
                    'reflujo': reflujo,
                    'psv': psv,
                    'hallazgos': hallazgos
                })

        # 6. Guardar el documento (padre + hijos se guardan juntos)
        doc.save(ignore_permissions=False)
        frappe.db.commit()

        return doc.name   # Retorna el nombre del Eco Doppler guardado

    except Exception as e:
        frappe.log_error(message=frappe.get_traceback(), title="Error al guardar Doppler")
        frappe.throw(f"Error al guardar en la Historia Clínica: {str(e)}")
