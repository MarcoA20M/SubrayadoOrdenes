import os
import fitz
import tempfile
from typing import List
import json
from flask import Flask, request, send_file
from flask_cors import CORS

app = Flask(__name__)

# Configuración CORS más robusta
CORS(app, resources={
    r"/procesar_pdf": {
        "origins": ["http://localhost:8080", "http://localhost:3000", "http://127.0.0.1:8080"],
        "methods": ["POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
        "supports_credentials": True
    }
})

# Headers CORS manuales para mayor seguridad
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', 'http://localhost:8080')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS, GET')
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response

def highlight_pdf_with_rondas_folios(
    pdf_path: str,
    search_texts: List[str],
    cargas: List[dict],
    num_casillas_extra: int = 14,
    max_pages: int = 100  # Límite de páginas para evitar timeout
) -> str:
    """
    Procesa PDF y añade anotaciones optimizado para Render
    """
    try:
        doc = fitz.open(pdf_path)
        temp_output_fd, temp_output_path = tempfile.mkstemp(suffix=".pdf")
        os.close(temp_output_fd)
        
        # Mapa optimizado de folios
        folio_to_info_map = {}
        for carga in cargas:
            folio = str(carga.get("folio", "")).strip().upper()
            if folio:
                folio_to_info_map[folio] = {
                    "ronda": carga.get("ronda", 1),
                    "maquina": carga.get("maquina", "N/A"),
                    "operario": carga.get("operario", "N/A")
                }
        
        folios_ids_from_cargas = list(folio_to_info_map.keys())
        search_flags = fitz.TEXT_DEHYPHENATE | fitz.TEXT_PRESERVE_WHITESPACE
        
        # Constantes para anotaciones
        X_OFFSET_ANNOTATIONS = 0
        Y_OFFSET_ABOVE_DEPT = -13
        X_OFFSET_RIGHT_OF_LABEL = 5
        ANNOTATION_WIDTH = 200
        ANNOTATION_HEIGHT = 15

        # Limitar número de páginas procesadas
        total_pages = min(len(doc), max_pages)
        
        for page_idx in range(total_pages):
            page = doc[page_idx]
            all_folios_rects_on_page = []
            
            # Buscar folios en la página actual
            for folio_id in folios_ids_from_cargas:
                try:
                    instances = page.search_for(folio_id, flags=search_flags)
                    for inst in instances:
                        all_folios_rects_on_page.append({'folio_id': folio_id, 'rect': inst})
                except:
                    continue

            def find_closest_folio_data(target_rect):
                if not all_folios_rects_on_page:
                    return None
                closest_folio_data = None
                min_distance = float('inf')
                target_center_x = target_rect.x0 + target_rect.width / 2
                target_center_y = target_rect.y0 + target_rect.height / 2
                
                for folio_entry in all_folios_rects_on_page:
                    folio_rect = folio_entry['rect']
                    folio_center_x = folio_rect.x0 + folio_rect.width / 2
                    folio_center_y = folio_rect.y0 + folio_rect.height / 2
                    distance = ((target_center_x - folio_center_x)**2 + (target_center_y - folio_center_y)**2)**0.5
                    if distance < min_distance:
                        min_distance = distance
                        closest_folio_data = folio_to_info_map[folio_entry['folio_id']]
                return closest_folio_data

            # Procesar departamentos
            try:
                for dept_rect in page.search_for("Departamento", flags=search_flags):
                    data = find_closest_folio_data(dept_rect)
                    if data:
                        ronda_text = f"Ronda {data['ronda']}"
                        text_rect = fitz.Rect(
                            dept_rect.x0 + X_OFFSET_ANNOTATIONS,
                            dept_rect.y0 + Y_OFFSET_ABOVE_DEPT,
                            dept_rect.x0 + X_OFFSET_ANNOTATIONS + ANNOTATION_WIDTH,
                            dept_rect.y0 + Y_OFFSET_ABOVE_DEPT + ANNOTATION_HEIGHT
                        )
                        annot = page.add_freetext_annot(text_rect, ronda_text, fontsize=10, fontname="helv", text_color=(0,0,0))
                        annot.update()
            except:
                pass

            # Procesar operador
            try:
                for operador_rect in page.search_for("Operador:", flags=search_flags):
                    data = find_closest_folio_data(operador_rect)
                    if data:
                        text_rect = fitz.Rect(
                            operador_rect.x1 + X_OFFSET_RIGHT_OF_LABEL,
                            operador_rect.y0,
                            operador_rect.x1 + X_OFFSET_RIGHT_OF_LABEL + ANNOTATION_WIDTH,
                            operador_rect.y0 + ANNOTATION_HEIGHT
                        )
                        annot = page.add_freetext_annot(text_rect, data['operario'], fontsize=10, fontname="helv", text_color=(0,0,0))
                        annot.update()
            except:
                pass

            # Procesar equipo
            try:
                for equipo_rect in page.search_for("Equipo:", flags=search_flags):
                    data = find_closest_folio_data(equipo_rect)
                    if data:
                        text_rect = fitz.Rect(
                            equipo_rect.x1 + X_OFFSET_RIGHT_OF_LABEL,
                            equipo_rect.y0,
                            equipo_rect.x1 + X_OFFSET_RIGHT_OF_LABEL + ANNOTATION_WIDTH,
                            equipo_rect.y0 + ANNOTATION_HEIGHT
                        )
                        annot = page.add_freetext_annot(text_rect, data['maquina'], fontsize=10, fontname="helv", text_color=(0,0,0))
                        annot.update()
            except:
                pass

            # Procesar términos de búsqueda (limitado a 50 por página)
            search_terms_processed = 0
            for search_text in search_texts:
                if search_terms_processed >= 50:  # Límite por página
                    break
                    
                try:
                    code = search_text.strip().upper()
                    if not code:
                        continue
                    
                    instances = page.search_for(code, flags=search_flags)
                    if not instances:
                        continue
                        
                    last_instance = instances[-1]
                    estimated_char_width = last_instance.width / len(code)
                    estimated_width_per_casilla = 15 if estimated_char_width < 5 else estimated_char_width * 3
                    extra_width = estimated_width_per_casilla * num_casillas_extra
                    extended_rect = fitz.Rect(last_instance.x0, last_instance.y0, last_instance.x1 + extra_width, last_instance.y1)
                    
                    highlight = page.add_highlight_annot(extended_rect)
                    highlight.set_colors(stroke=(0.7, 0.7, 0.7))
                    highlight.update()
                    
                    search_terms_processed += 1
                    
                except Exception as e:
                    print(f"Error resaltando {search_text}: {e}")
                    continue

        # Guardar optimizado
        doc.save(temp_output_path, garbage=4, deflate=True, clean=True)
        doc.close()
        return temp_output_path
        
    except Exception as e:
        print(f"Error crítico en highlight_pdf_with_rondas_folios: {e}")
        raise

@app.route("/procesar_pdf", methods=["POST", "OPTIONS"])
def procesar_pdf():
    """
    Endpoint principal para procesar PDFs
    """
    input_path = None
    output_path = None
    
    try:
        # Manejar preflight requests
        if request.method == "OPTIONS":
            return "", 200
            
        if "file" not in request.files:
            return json.dumps({"error": "No se subió ningún archivo"}), 400

        # Obtener datos de cargas
        cargas_data = request.form.get("cargas", "[]")
        try:
            cargas = json.loads(cargas_data)
        except json.JSONDecodeError:
            return json.dumps({"error": "Formato de 'cargas' inválido"}), 400

        file = request.files["file"]

        # Validar tipo de archivo
        if not file.filename.lower().endswith('.pdf'):
            return json.dumps({"error": "Solo se permiten archivos PDF"}), 400

        # Guardar archivo temporal
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_in:
            file.save(tmp_in.name)
            input_path = tmp_in.name

        # Lista optimizada de términos de búsqueda
        search_terms = [
            "AAE70", "AAM10", "AAM11", "AAM12", "AAN20", "AAN30", "AAN50",
            "AAP10", "AAY10", "ABA10", "ABA20", "ABA30", "ABA31", "ABB20",
            # ... (tu lista completa de términos)
            "AAB80", "AAS10", "AAV10", "AAH30", "AHG10"
        ]

        # Procesar PDF
        output_path = highlight_pdf_with_rondas_folios(
            input_path, 
            search_terms, 
            cargas,
            max_pages=50  # Limitar a 50 páginas máximo
        )

        # Enviar respuesta
        return send_file(
            output_path,
            as_attachment=True,
            download_name="resultado_rondas_y_folios.pdf",
            mimetype="application/pdf"
        )

    except Exception as e:
        print(f"Error procesando PDF: {str(e)}")
        return json.dumps({"error": f"Error procesando PDF: {str(e)}"}), 500

    finally:
        # Limpieza de archivos temporales
        try:
            if input_path and os.path.exists(input_path):
                os.remove(input_path)
            if output_path and os.path.exists(output_path):
                os.remove(output_path)
        except:
            pass

@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint de salud para verificar que el servidor está funcionando"""
    return json.dumps({"status": "healthy", "message": "Servidor funcionando correctamente"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003, debug=True)