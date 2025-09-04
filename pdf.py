import os
import fitz
import tempfile
from typing import List
import json
from flask import Flask, request, send_file, jsonify
from flask_cors import CORS

# En un entorno de producción como Render, el frontend debe llamar a la URL pública del servicio.
# El puerto 8080 solo se usa para desarrollo local, por lo que lo hemos quitado del código.
# Gunicorn se encargará de usar la variable de entorno $PORT en Render.

app = Flask(__name__)
# Configuración más explícita de CORS para permitir todas las solicitudes
CORS(app, resources={r"/*": {"origins": "*"}})

def highlight_pdf_with_rondas_folios(
    pdf_path: str,
    search_texts: List[str],
    cargas: List[dict],
    num_casillas_extra: int = 14,
) -> str:
    doc = fitz.open(pdf_path)

    temp_output_fd, temp_output_path = tempfile.mkstemp(suffix=".pdf")
    os.close(temp_output_fd)


    folio_to_info_map = {
        str(carga.get("folio", "")).strip().upper(): {
            "ronda": carga.get("ronda", 1),
            "maquina": carga.get("maquina", "N/A"),
            "operario": carga.get("operario", "N/A")
        }
        for carga in cargas if carga.get("folio") is not None
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

        # Helper para buscar el folio más cercano
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

        # --- Ronda sobre "Departamento" ---
        dept_instances = page.search_for("Departamento", flags=search_flags)
        for dept_rect in dept_instances:
            relevant_folio_data = find_closest_folio_data(dept_rect)
            if relevant_folio_data:
                ronda_text = f"Ronda {relevant_folio_data['ronda']}"
                text_rect = fitz.Rect(
                    dept_rect.x0 + X_OFFSET_ANNOTATIONS,
                    dept_rect.y0 + Y_OFFSET_ABOVE_DEPT,
                    dept_rect.x0 + X_OFFSET_ANNOTATIONS + ANNOTATION_WIDTH,
                    dept_rect.y0 + Y_OFFSET_ABOVE_DEPT + ANNOTATION_HEIGHT
                )
                annot = page.add_freetext_annot(
                    text_rect,
                    ronda_text,
                    fontsize=10,
                    fontname="helvB",
                    text_color=(0, 0, 0),
                    fill_color=None,
                    align=0
                )
                annot.update()

        # --- Operador ---
        operador_instances = page.search_for("Operador:", flags=search_flags)
        for operador_rect in operador_instances:
            relevant_folio_data = find_closest_folio_data(operador_rect)
            if relevant_folio_data:
                operario_text = f"{relevant_folio_data['operario']}"
                text_rect = fitz.Rect(
                    operador_rect.x1 + X_OFFSET_RIGHT_OF_LABEL,
                    operador_rect.y0,
                    operador_rect.x1 + X_OFFSET_RIGHT_OF_LABEL + ANNOTATION_WIDTH,
                    operador_rect.y0 + ANNOTATION_HEIGHT
                )
                annot = page.add_freetext_annot(
                    text_rect,
                    operario_text,
                    fontsize=10,
                    fontname="helvB",
                    text_color=(0, 0, 0),
                    fill_color=None,
                    align=0
                )
                annot.update()

        # --- Equipo ---
        equipo_instances = page.search_for("Equipo:", flags=search_flags)
        for equipo_rect in equipo_instances:
            relevant_folio_data = find_closest_folio_data(equipo_rect)
            if relevant_folio_data:
                maquina_text = f"{relevant_folio_data['maquina']}"
                text_rect = fitz.Rect(
                    equipo_rect.x1 + X_OFFSET_RIGHT_OF_LABEL,
                    equipo_rect.y0,
                    equipo_rect.x1 + X_OFFSET_RIGHT_OF_LABEL + ANNOTATION_WIDTH,
                    equipo_rect.y0 + ANNOTATION_HEIGHT
                )
                annot = page.add_freetext_annot(
                    text_rect,
                    maquina_text,
                    fontsize=10,
                    fontname="helvB",
                    text_color=(0, 0, 0),
                    fill_color=None,
                    align=0
                )
                annot.update()

        # --- Resaltado de casillas extra ---
        for search_text in search_texts:
            text_instances = page.search_for(search_text, flags=search_flags)
            if text_instances:
                last_instance = text_instances[-1]
                estimated_char_width = last_instance.width / len(search_text) if search_text else 10
                estimated_width_per_casilla = 15 if estimated_char_width < 5 else estimated_char_width * 3
                extra_width = estimated_width_per_casilla * num_casillas_extra
                extended_rect = fitz.Rect(
                    last_instance.x0, last_instance.y0,
                    last_instance.x1 + extra_width, last_instance.y1
                )
                highlight = page.add_highlight_annot(extended_rect)
                highlight.set_colors(stroke=(0.7, 0.7, 0.7))
                highlight.update()

    doc.save(temp_output_path)
    doc.close()
    return temp_output_path


@app.route("/procesar_pdf", methods=["POST"])
def procesar_pdf():
    """
    Función que maneja la solicitud POST para procesar un archivo PDF.

    **NOTA IMPORTANTE SOBRE EL TIEMPO DE ESPERA (TIMEOUT):**
    Los registros de error indican que el trabajador de Gunicorn se está agotando
    el tiempo de espera (`WORKER TIMEOUT`), lo que hace que el proceso falle
    y el servidor se reinicie. Esto ocurre porque el procesamiento de PDF para un
    documento grande y una larga lista de términos de búsqueda tarda más de 30 segundos
    (el tiempo de espera predeterminado de Gunicorn en Render).

    Para solucionar esto, necesitas aumentar el tiempo de espera de Gunicorn en la
    configuración de tu servicio en Render. En el panel de control de Render, ve a:
    Settings -> Environment -> Add Environment Variable.

    Añade las siguientes variables y valores:
    - **Key:** `GUNICORN_CMD_ARGS`
    - **Value:** `--timeout 120` (o un valor mayor, como 300, si es necesario)

    Esto aumentará el tiempo de espera a 120 segundos, dándole al servidor más
    tiempo para procesar la solicitud.
    """
    try:
        if "file" not in request.files:
            return jsonify({"error": "No se subió ningún archivo."}), 400

        cargas_data = request.form.get("cargas", "[]")
        try:
            cargas = json.loads(cargas_data)
        except json.JSONDecodeError as e:
            print(f"Error decodificando 'cargas_data': {e}")
            return jsonify({"error": "Formato de 'cargas' inválido."}), 400

        file = request.files["file"]

        input_fd, input_path = tempfile.mkstemp(suffix=".pdf")
        os.close(input_fd)
        file.save(input_path)

        search_terms = [
        "AAE70", "AAM10", "AAM11", "AAM12", "AAN20", "AAN30", "AAN50",
        "AAP10", "AAY10", "ABA10", "ABA20", "ABA30", "ABA31", "ABB20",
        "ABL10", "ABV30", "ACA10", "ACC10", "ACC20", "ACT20", "ADC10",
        "ADC30", "ADG10", "ADI10", "ADI20", "ADI30", "ADL10", "ADN10",
        "ADN11", "ADN12", "ADN13", "ADN14", "ADN30", "ADO10", "ADP10",
        "ADP20", "ADR10", "ADS10", "ADT20", "ADV10", "ADV30", "AED10"
    ];

        output_path = highlight_pdf_with_rondas_folios(
            input_path,
            search_terms,
            cargas
        )

        response = send_file(
            output_path,
            as_attachment=True,
            download_name=f"resultado_rondas_y_folios.pdf",
            mimetype="application/pdf"
        )

        @response.call_on_close
        def cleanup():
            try:
                os.remove(input_path)
                os.remove(output_path)
            except OSError as e:
                print(f"Error durante la limpieza de archivos temporales: {e}")

        return response
    
    except Exception as e:
        print(f"Ocurrió un error inesperado en la ruta /procesar_pdf: {e}")
        return jsonify({"error": "Ocurrió un error interno del servidor."}), 500
