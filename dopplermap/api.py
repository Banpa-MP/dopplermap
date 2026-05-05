import frappe
import google.generativeai as genai

@frappe.whitelist()
def consultar_gemini(prompt):
    """
    Función puente entre ERPNext y la API de Gemini.
    Oculta la API Key en el servidor para evitar que sea extraída desde el Frontend (React).
    """
    
    # IMPORTANTE: Debes crear un "Single Doctype" en Frappe (ej. 'Doppler Settings') 
    # que tenga un campo llamado 'gemini_api_key' para guardar tu clave privada.
    api_key = frappe.db.get_single_value('Doppler Settings', 'gemini_api_key')
    
    if not api_key:
        frappe.throw("La API Key de Gemini no está configurada en el servidor. Por favor configúrala en 'Doppler Settings'.")

    #        
    # Inicializa el cliente de Gemini
    genai.configure(api_key=api_key)
    
    try:
        # Usa el modelo más rápido y económico para texto
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        # Ejecuta el prompt que llega desde React
        response = model.generate_content(prompt)
        
        # Retorna el texto puro para que el Frontend lo renderice
        return response.text
        
    except Exception as e:
        # Si falla, guarda el error detallado en el "Error Log" de Frappe
        frappe.log_error(message=str(e), title="Error Interno en Gemini API")
        frappe.throw("Error de conexión con la IA. Se ha generado un reporte en el Error Log.")
