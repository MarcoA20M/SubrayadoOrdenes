import os
import fitz  # PyMuPDF
import tempfile
from typing import List
import json
from flask import Flask, request, send_file
from flask_cors import CORS

app = Flask(__name__)

# Configurar CORS para aceptar cualquier origen
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

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
            instances = page.search_for(search_text, flags=search_flags)
            if instances:
                last_instance = instances[-1]
                estimated_char_width = last_instance.width / len(search_text) if search_text else 10
                estimated_width_per_casilla = 15 if estimated_char_width < 5 else estimated_char_width * 3
                extra_width = estimated_width_per_casilla * num_casillas_extra
                extended_rect = fitz.Rect(last_instance.x0, last_instance.y0, last_instance.x1 + extra_width, last_instance.y1)
                highlight = page.add_highlight_annot(extended_rect)
                highlight.set_colors(stroke=(0.7, 0.7, 0.7))
                highlight.update()

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

    search_terms = [
        # TODOS tus códigos completos aquí
        "AAE70", "AAM10", "AAM11", "AAM12", "AAN20", "AAN30", "AAN50",
        "AAP10", "AAY10", "ABA10", "ABA20", "ABA30", "ABA31", "ABB20",
        "ABL10", "ABV30", "ACA10", "ACC10", "ACC20", "ACT20", "ADC10",
        "ADC30", "ADG10", "ADI10", "ADI20", "ADI30", "ADL10", "ADN10",
        "ADN11", "ADN12", "ADN13", "ADN14", "ADN30", "ADO10", "ADP10",
        "ADP20", "ADR10", "ADS10", "ADT20", "ADV10", "ADV30", "AED10",
        "AEE10", "AFM10", "AFW10", "AHA10", "AHS20", "AHU30", "AHU40",
        "AHU50", "AIC30", "AIM10", "AMP10", "ANR10", "ANV10", "APC10",
        "APC20", "APC34", "APZ10", "ASC10", "ASF10", "ASO10", "AST10",
        "ATD10", "ATI11", "ATI20", "ATI30", "ATT20", "ATT30", "ATT40",
        "CAC10", "CAH10", "CAT10", "CCA20", "CCA40", "CCH10", "CCH11",
        "CCH70", "CCM55", "CCM60", "CCP10", "CCP15", "CCU20", "CEE20",
        "CEH10", "CFC10", "CFP10", "CML10", "CPE10", "CPF10", "CVG10",
        "DSA10", "EAA10", "EAV10", "ECE20", "ECE22", "ECN20", "ENV10",
        "ERA10", "ERA20", "ERA50", "ERA51", "ERA53", "ERA54", "MOW10",
        "MQC10", "MRI10", "NAB10", "NEO10", "NSE10", "PAC05", "PAC10",
        "PAC15", "PAC20", "PAC30", "PAF10", "PAI10", "PAI20", "PAL05",
        "PAL60", "PAL80", "PAL85", "PAL90", "PAL95", "PAP57", "PAP58",
        "PAP59", "PAP60", "PAS51", "PAS54", "PAS55", "PAS56", "PAS58",
        "PAU52", "PAU53", "PAU57", "PAV40", "PAZ10", "PBF10", "PBF41",
        "PBO15", "PBT10", "PCA20", "PCB11", "PCB13", "PCN14", "PCR10",
        "PCS10", "PCS20", "PCS30", "PDA20", "PDA30", "PDA40", "PDN10",
        "PDR10", "PDV20", "PDV30", "PGM20", "PHA10", "PHA20", "PHA30",
        "PHA40", "PHA72", "PIN10", "PKF10", "PMF21", "PNA70", "PNH30",
        "PNH40", "PNH50", "PNH60", "PNM10", "PNP40", "PNR40", "POF10",
        "POM20", "POP21", "POR25", "PPC20", "PPS10", "PQF11", "PQF20",
        "PRB10", "PRB20", "PRC40", "PRE10", "PRF10", "PRF20", "PRH40",
        "PRM05", "PRM40", "PRN40", "PRO10", "PRP4", "PRP4-B", "PRP6",
        "PRR50", "PRS10", "PRT10", "PRV40", "PSB41", "PSC41", "PSE41",
        "PSR41", "PSS41", "PSY17", "PTA10", "PTR10", "PTR11", "PVC10",
        "PVC74", "PVF08", "PVF15", "PVF41", "PVI10", "PVI30", "PVM41",
        "PXC10", "PXC20", "PXC30", "PXC40", "PYF10", "RAA10", "RAA20",
        "RAC10", "RAC20", "RAH10", "RAH20", "RAH35", "RAL10", "RAM30",
        "RAO10", "RAP10", "RAR10", "RAS10", "RAS30", "RAS40", "RAS50",
        "RAT10", "RAT20", "RAT30", "RAT40", "RAT41", "RBA10", "RBA30",
        "RBA40", "RBA50", "RBA60", "RCO10", "RCU10", "REA10", "REC10",
        "REM20", "REP10", "REP11", "REP20", "REV10", "RHA30", "RHU20",
        "RIE40", "RIE60", "RLA10", "RLA30", "RLC30", "RLD30", "RLE30",
        "RPA05", "RPA10", "RPE30", "RPR10", "RPS10", "RPT10", "RPT15",
        "RRE10", "RRN20", "RRZ10", "RSA10", "RSE10", "RST10", "RTA10",
        "RTA20", "RTE10", "RTP10", "RTP20", "RVA40", "SAA10", "SAC10",
        "SAC20", "SAE20", "SAR10", "SAT10", "SBA10", "SBC20", "SBL10",
        "SBU10", "SCH10", "SET10", "SFM10", "SIP10", "SLP01", "SME10",
        "SMI10", "SNI10", "SPM10", "SSO10", "STO10", "TAM30", "TMB10",
        "TMB11", "TMB12", "TRX20", "TRX40", "TTI06", "TTI50", "VPS10",
        "AAB80", "AAS10", "AAV10", "AAH30", "AHG10"
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
        # Limpieza de archivos en caso de error
        try:
            os.remove(input_path)
        except OSError:
            pass
        return json.dumps({"error": str(e)}), 500, {'Access-Control-Allow-Origin': '*'}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003, debug=True)
