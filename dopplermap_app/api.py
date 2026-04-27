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
@frappe.whitelist()
def guardar_doppler_frontend(encounter_id, sistema, reporte_ia, matriz_datos):
    """
    Recibe la orden de 'Culminar Estudio' desde React y guarda la información
    en el encuentro médico correspondiente.
    """
    if not encounter_id:
        frappe.throw("No se proporcionó un ID de Encuentro.")

    try:
        # 1. Cargar el documento original de ERPNext
        doc = frappe.get_doc("Vascular Encounter", encounter_id)
        
        # 2. Mapear los datos a los campos de tu DocType
        # NOTA: Verifica que estos nombres de campos (fieldnames) coincidan con los tuyos
        doc.sistema_evaluado = sistema         
        doc.reporte_ecografico = reporte_ia    
        doc.datos_json_mapa = matriz_datos     
        
        # 3. Guardar cambios
        doc.save(ignore_permissions=False)
        frappe.db.commit() # Asegura la escritura en disco
        
        return "OK"
        
    except Exception as e:
        frappe.log_error(message=frappe.get_traceback(), title="Error al guardar Doppler")
        frappe.throw(f"Error al guardar en la Historia Clínica: {str(e)}")
