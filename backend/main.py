from a1_pdf_generator import A1VerificationPDFGenerator

@app.post("/auditar-a1")
async def auditar_e_gerar_a1(file: UploadFile = File(...)):
    filename = file.filename or "desenho.dwg"
    ext = os.path.splitext(filename)[1].lower()
    base_name = os.path.splitext(filename)[0]

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        shutil.copyfileobj(file.file, tmp)
        input_path = tmp.name

    dxf_path = input_path
    converted_temporarily = False

    try:
        if ext == ".dwg":
            dxf_path = converter_dwg_para_dxf(input_path)
            converted_temporarily = True

        doc = ezdxf.readfile(dxf_path)
        audit_result = executar_auditoria_completa(doc, filename)

        # Gera o relatório em ISO A1 Paisagem (841 x 594 mm)
        pdf_filename = f"Verificacao_A1_{base_name}.pdf"
        pdf_gen = A1VerificationPDFGenerator(output_dir=REPORTS_DIR)
        pdf_gen.generate(doc, audit_result, pdf_filename)

        audit_result["pdf_filename"] = pdf_filename
        return audit_result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro no processamento: {str(e)}")
    finally:
        if os.path.exists(input_path):
            os.remove(input_path)
        if converted_temporarily and os.path.exists(dxf_path):
            os.remove(dxf_path)

# Mantém rota anterior para compatibilidade
@app.post("/auditar-a3")
async def auditar_a3_alias(file: UploadFile = File(...)):
    return await auditar_e_gerar_a1(file)
