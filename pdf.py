import os
import fitz  # PyMuPDF
import tempfile
from typing import List
import json
from flask import Flask, request, send_file
from flask_cors import CORS

app = Flask(__name__)
# Permitir CORS desde cualquier origen
CORS(app, resources={r"/*": {"origins": "*"}})

def highlight_pdf_with_rondas_folios(
    pdf_path: str,
    search_texts: List[str],
    cargas: List[dict],
    num_casillas_extra: int = 14,
) -> str:
    doc = fitz.open(pdf_path)

    # Archivo temporal de salida
    temp_output_fd, temp_output_path = tempfile.mkstemp(suffix=".pdf")
    os.close(temp_output_fd)

    # Sanitizar folios
    folio_to_info_map = {
        str(carga.get("folio", "")).strip().upper(): {
            "ronda": carga.get("ronda", 1),
            "maquina": carga.get("maquina", "N/A"),
            "operario": carga.get("operario", "N/A")
        }
        for carga in cargas if carga.get("folio")
    }
    folios_ids_from_cargas = list(folio_to_info_map.keys())

    search_flags = fitz.TEXT_DEHYPHENATE | fitz.TEXT_PRESERVE_WHITESPACE

    X_OFFSET_ANNOTATIONS = 0
    Y_OFFSET_ABOVE_DEPT = -13
    X_OFFSET_RIGHT_OF_LABEL = 5
    ANNOTATION_WIDTH = 200
    ANNOTATION_HEIGHT = 15

    for page_idx, page in enumerate(doc):
        all_folios_rects_on_page = []
        for folio_id in folios_ids_from_cargas:
            instances = page.search_for(folio_id, flags=search_flags)
            for inst in instances:
                all_folios_rects_on_page.append({'folio_id': folio_id, 'rect': inst})

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

        # --- Departamento ---
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
                annot = page.add_freetext_annot(text_rect, ronda_text, fontsize=10, fontname="helvB", text_color=(0,0,0))
                annot.update()

        # --- Operador ---
        for operador_rect in page.search_for("Operador:", flags=search_flags):
            data = find_closest_folio_data(operador_rect)
            if data:
                text_rect = fitz.Rect(
                    operador_rect.x1 + X_OFFSET_RIGHT_OF_LABEL,
                    operador_rect.y0,
                    operador_rect.x1 + X_OFFSET_RIGHT_OF_LABEL + ANNOTATION_WIDTH,
                    operador_rect.y0 + ANNOTATION_HEIGHT
                )
                annot = page.add_freetext_annot(text_rect, data['operario'], fontsize=10, fontname="helvB", text_color=(0,0,0))
                annot.update()

        # --- Equipo ---
        for equipo_rect in page.search_for("Equipo:", flags=search_flags):
            data = find_closest_folio_data(equipo_rect)
            if data:
                text_rect = fitz.Rect(
                    equipo_rect.x1 + X_OFFSET_RIGHT_OF_LABEL,
                    equipo_rect.y0,
                    equipo_rect.x1 + X_OFFSET_RIGHT_OF_LABEL + ANNOTATION_WIDTH,
                    equipo_rect.y0 + ANNOTATION_HEIGHT
                )
                annot = page.add_freetext_annot(text_rect, data['maquina'], fontsize=10, fontname="helvB", text_color=(0,0,0))
                annot.update()

        # --- Resaltado de códigos ---
        for search_text in search_texts:
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
            except Exception as e:
                print(f"Error resaltando {search_text}: {e}")
                continue

    doc.save(temp_output_path)
    doc.close()
    return temp_output_path

@app.route("/procesar_pdf", methods=["POST"])
def procesar_pdf():
    if "file" not in request.files:
        return "No se subió ningún archivo", 400

    cargas_data = request.form.get("cargas", "[]")
    try:
        cargas = json.loads(cargas_data)
    except json.JSONDecodeError:
        return "Formato de 'cargas' inválido", 400

    file = request.files["file"]

    # Archivo temporal de entrada
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_in:
        file.save(tmp_in.name)
        input_path = tmp_in.name

    # --- Lista completa de códigos ---
    search_terms = [
        "AAE70", "AAM10", "AAM11", "AAM12", "AAN20", "AAN30", "AAN50",
        "AAP10", "AAY10", "ABA10", "ABA20", "ABA30", "ABA31", "ABB20",
        "ABL10", "ABV30", "ACA10", "ACC10", "ACC20", "ACT20", "ADC10",
        # …agrega todos tus códigos aquí…
        "ADC30", "ADG10", "ADI10", "ADI20", "ADI30", "ADL10", "ADN10",
        "ADN11", "ADN12", "ADN13", "ADN14", "ADN30", "ADO10", "ADP10",
        "ADP20", "ADR10", "ADS10", "ADT20", "ADV10", "ADV30", "AED10",
        "AEE10", "AFM10", "AFW10", "AHA10", "AHS20", "AHU30", "AHU40",
        "AHU50", "AIC30", "AIM10", "AMP10", "ANR10", "ANV10", "APC10"
    ]

    try:
        output_path = highlight_pdf_with_rondas_folios(input_path, search_terms, cargas)

        response = send_file(
            output_path,
            as_attachment=True,
            download_name="resultado_rondas_y_folios.pdf",
            mimetype="application/pdf"
        )

        @response.call_on_close
        def cleanup():
            try:
                os.remove(input_path)
                os.remove(output_path)
            except OSError:
                pass

        return response

    except Exception as e:
        try:
            os.remove(input_path)
        except OSError:
            pass
        return f"Error procesando PDF: {str(e)}", 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003, debug=True)
