import os
import fitz  # PyMuPDF
import tempfile
from typing import List
import json
from flask import Flask, request, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

def highlight_pdf_with_rondas_folios(pdf_path: str, search_texts: List[str], cargas: List[dict], num_casillas_extra: int = 14) -> str:
    doc = fitz.open(pdf_path)

    # Archivo temporal de salida
    temp_output_fd, temp_output_path = tempfile.mkstemp(suffix=".pdf")
    os.close(temp_output_fd)

    # Crear mapa de folios
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

    # Procesamiento por página
    for page in doc:
        # Precalcular todas las posiciones de folios de la página
        all_folios_rects_on_page = []
        for folio_id in folios_ids_from_cargas:
            instances = page.search_for(folio_id, flags=search_flags)
            for inst in instances:
                all_folios_rects_on_page.append({'folio_id': folio_id, 'rect': inst})

        # Función para obtener folio más cercano
        def find_closest_folio_data(target_rect):
            if not all_folios_rects_on_page:
                return None
            closest_data = None
            min_distance = float('inf')
            tx = target_rect.x0 + target_rect.width / 2
            ty = target_rect.y0 + target_rect.height / 2
            for f in all_folios_rects_on_page:
                fr = f['rect']
                fx = fr.x0 + fr.width / 2
                fy = fr.y0 + fr.height / 2
                d = ((tx - fx)**2 + (ty - fy)**2)**0.5
                if d < min_distance:
                    min_distance = d
                    closest_data = folio_to_info_map[f['folio_id']]
            return closest_data

        # Anotaciones Departamento
        for dept_rect in page.search_for("Departamento", flags=search_flags):
            data = find_closest_folio_data(dept_rect)
            if data:
                text_rect = fitz.Rect(dept_rect.x0 + X_OFFSET_ANNOTATIONS,
                                      dept_rect.y0 + Y_OFFSET_ABOVE_DEPT,
                                      dept_rect.x0 + X_OFFSET_ANNOTATIONS + ANNOTATION_WIDTH,
                                      dept_rect.y0 + Y_OFFSET_ABOVE_DEPT + ANNOTATION_HEIGHT)
                annot = page.add_freetext_annot(text_rect, f"Ronda {data['ronda']}", fontsize=10, fontname="helvB", text_color=(0,0,0))
                annot.update()

        # Anotaciones Operador
        for op_rect in page.search_for("Operador:", flags=search_flags):
            data = find_closest_folio_data(op_rect)
            if data:
                text_rect = fitz.Rect(op_rect.x1 + X_OFFSET_RIGHT_OF_LABEL,
                                      op_rect.y0,
                                      op_rect.x1 + X_OFFSET_RIGHT_OF_LABEL + ANNOTATION_WIDTH,
                                      op_rect.y0 + ANNOTATION_HEIGHT)
                annot = page.add_freetext_annot(text_rect, data['operario'], fontsize=10, fontname="helvB", text_color=(0,0,0))
                annot.update()

        # Anotaciones Equipo
        for eq_rect in page.search_for("Equipo:", flags=search_flags):
            data = find_closest_folio_data(eq_rect)
            if data:
                text_rect = fitz.Rect(eq_rect.x1 + X_OFFSET_RIGHT_OF_LABEL,
                                      eq_rect.y0,
                                      eq_rect.x1 + X_OFFSET_RIGHT_OF_LABEL + ANNOTATION_WIDTH,
                                      eq_rect.y0 + ANNOTATION_HEIGHT)
                annot = page.add_freetext_annot(text_rect, data['maquina'], fontsize=10, fontname="helvB", text_color=(0,0,0))
                annot.update()

        # Resaltado de códigos en lotes
        batch_size = 50
        for i in range(0, len(search_texts), batch_size):
            batch = search_texts[i:i+batch_size]
            for code in batch:
                instances = page.search_for(code, flags=search_flags)
                if instances:
                    last_inst = instances[-1]
                    w = last_inst.width / len(code) if code else 10
                    width_per_casilla = 15 if w < 5 else w * 3
                    extended_rect = fitz.Rect(last_inst.x0, last_inst.y0, last_inst.x1 + width_per_casilla*num_casillas_extra, last_inst.y1)
                    hl = page.add_highlight_annot(extended_rect)
                    hl.set_colors(stroke=(0.7,0.7,0.7))
                    hl.update()

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

    # Lista completa de códigos
    search_terms = [
        "AAE70","AAM10","AAM11","AAM12","AAN20","AAN30","AAN50","AAP10","AAY10","ABA10",
        "ABA20","ABA30","ABA31","ABB20","ABL10","ABV30","ACA10","ACC10","ACC20","ACT20","ADC10",
        "ADC30","ADG10","ADI10","ADI20","ADI30","ADL10","ADN10","ADN11","ADN12","ADN13","ADN14",
        "ADN30","ADO10","ADP10","ADP20","ADR10","ADS10","ADT20","ADV10","ADV30","AED10","AEE10",
        "AFM10","AFW10","AHA10","AHS20","AHU30","AHU40","AHU50","AIC30","AIM10","AMP10","ANR10",
        "ANV10","APC10","APC20","APC34","APZ10","ASC10","ASF10","ASO10","AST10","ATD10","ATI11",
        "ATI20","ATI30","ATT20","ATT30","ATT40","CAC10","CAH10","CAT10","CCA20","CCA40","CCH10",
        "CCH11","CCH70","CCM55","CCM60","CCP10","CCP15","CCU20","CEE20","CEH10","CFC10","CFP10",
        "CML10","CPE10","CPF10","CVG10","DSA10","EAA10","EAV10","ECE20","ECE22","ECN20","ENV10",
        "ERA10","ERA20","ERA50","ERA51","ERA53","ERA54","MOW10","MQC10","MRI10","NAB10","NEO10",
        "NSE10","PAC05","PAC10","PAC15","PAC20","PAC30","PAF10","PAI10","PAI20","PAL05","PAL60",
        "PAL80","PAL85","PAL90","PAL95","PAP57","PAP58","PAP59","PAP60","PAS51","PAS54","PAS55",
        "PAS56","PAS58","PAU52","PAU53","PAU57","PAV40","PAZ10","PBF10","PBF41","PBO15","PBT10",
        "PCA20","PCB11","PCB13","PCN14","PCR10","PCS10","PCS20","PCS30","PDA20","PDA30","PDA40",
        "PDN10","PDR10","PDV20","PDV30","PGM20","PHA10","PHA20","PHA30","PHA40","PHA72","PIN10",
        "PKF10","PMF21","PNA70","PNH30","PNH40","PNH50","PNH60","PNM10","PNP40","PNR40","POF10",
        "POM20","POP21","POR25","PPC20","PPS10","PQF11","PQF20","PRB10","PRB20","PRC40","PRE10",
        "PRF10","PRF20","PRH40","PRM05","PRM40","PRN40","PRO10","PRP4","PRP4-B","PRP6","PRR50",
        "PRS10","PRT10","PRV40","PSB41","PSC41","PSE41","PSR41","PSS41","PSY17","PTA10","PTR10",
        "PTR11","PVC10","PVC74","PVF08","PVF15","PVF41","PVI10","PVI30","PVM41","PXC10","PXC20",
        "PXC30","PXC40","PYF10","RAA10","RAA20","RAC10","RAC20","RAH10","RAH20","RAH35","RAL10",
        "RAM30","RAO10","RAP10","RAR10","RAS10","RAS30","RAS40","RAS50","RAT10","RAT20","RAT30",
        "RAT40","RAT41","RBA10","RBA30","RBA40","RBA50","RBA60","RCO10","RCU10","REA10","REC10",
        "REM20","REP10","REP11","REP20","REV10","RHA30","RHU20","RIE40","RIE60","RLA10","RLA30",
        "RLC30","RLD30","RLE30","RPA05","RPA10","RPE30","RPR10","RPS10","RPT10","RPT15","RRE10",
        "RRN20","RRZ10","RSA10","RSE10","RST10","RTA10","RTA20","RTE10","RTP10","RTP20","RVA40",
        "SAA10","SAC10","SAC20","SAE20","SAR10","SAT10","SBA10","SBC20","SBL10","SBU10","SCH10",
        "SET10","SFM10","SIP10","SLP01","SME10","SMI10","SNI10","SPM10","SSO10","STO10","TAM30",
        "TMB10","TMB11","TMB12","TRX20","TRX40","TTI06","TTI50","VPS10","AAB80","AAS10","AAV10",
        "AAH30","AHG10"
    ]

    try:
        output_path = highlight_pdf_with_rondas_folios(input_path, search_terms, cargas)
        response = send_file(output_path, as_attachment=True, download_name="resultado_rondas_y_folios.pdf", mimetype="application/pdf")

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
