import os
import base64
import hashlib
import secrets
import smtplib
import re
import tempfile 
from io import BytesIO
from datetime import datetime, timedelta
from email.message import EmailMessage
from textwrap import dedent
from typing import Optional, Tuple, List
import pandas as pd
import numpy as np
import streamlit as st
from passlib.context import CryptContext
from PIL import Image
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfgen import canvas
from streamlit.components.v1 import html as components_html
import json
import uuid  # Corrigido
import io # Adicionado para o Excel
import xlsxwriter # Adicionado para o Excel
import pytz 

# --- CONSTANTES DE IMAGEM (URLs) ---
FAVICON_URL = "https://github.com/lucasaccardo/vamos-frotas-sla/blob/main/assets/logo.png?raw=true"
LOGO_URL_LOGIN = "https://github.com/lucasaccardo/vamos-frotas-sla/blob/main/assets/logo.png?raw=true"
LOGO_URL_SIDEBAR = "https://github.com/lucasaccardo/vamos-frotas-sla/blob/main/assets/logo.png?raw=true"
# ------------------------------------

# --- Fuso Horário ---
tz_brasilia = pytz.timezone('America/Sao_Paulo')
# ------------------------------------


# --- Funções de Path e CSS ---
def resource_path(filename: str) -> str:
    try:
        base = os.path.dirname(__file__)
    except Exception:
        base = os.getcwd()
    return os.path.join(base, filename)

def load_css(file_path):
    full_path = resource_path(file_path)
    try:
        if os.path.exists(full_path):
            with open(full_path) as f:
                st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
        else:
            pass 
    except Exception as e:
        st.warning(f"Não foi possível carregar o 'estilo.css': {e}")
# --- FIM ---


# --- INICIALIZAÇÃO DO SUPABASE ---
from supabase import create_client, Client

url = st.secrets.get("SUPABASE_URL")
key = st.secrets.get("SUPABASE_KEY")

if not url or not key:
    st.error("Credenciais do Supabase (URL ou KEY) não encontradas. Verifique seus Secrets.")
    st.stop()

supabase: Client = create_client(url, key)
# ---------------------------------

# --- Conversor de JSON para Numpy/Pandas ---
def converter_json(obj):
    if isinstance(obj, (np.integer, np.int64)):
        return int(obj)
    if isinstance(obj, (np.floating, np.float64)):
        return float(obj)
    if isinstance(obj, (np.ndarray)):
        return obj.tolist()
    if isinstance(obj, (datetime, pd.Timestamp)):
        return obj.isoformat()
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")
# --- FIM ---

# --- Função de Relatório (Achatada) ---
def extrair_linha_relatorio(row, supabase_url=None):
    try:
        dados = json.loads(row["dados_json"])
    except Exception:
        dados = row["dados_json"]

    if row["tipo"] == "cenarios":
        melhor = dados.get("melhor", {})
        cliente = melhor.get("Cliente", "-")
        placa = melhor.get("Placa", "-")
        servico = melhor.get("Serviço", "-")
        valor_final = melhor.get("Total Final (R$)", "-")
    elif row["tipo"] == "sla_mensal":
        cliente = dados.get("cliente", "-")
        placa = dados.get("placa", "-")
        servico = dados.get("tipo_servico", "-")
        valor_final = f'R${dados.get("mensalidade", 0) - dados.get("desconto", 0):,.2f}'.replace(",", "X").replace(".", ",").replace("X", ".")
    else:
        cliente = placa = servico = valor_final = "-"

    pdf_link = ""
    if row["pdf_path"]:
        if supabase_url:
            pdf_link = f"{supabase_url}/pdfs/{row['pdf_path']}"
        else:
            pdf_link = "#" 

    return {
        "Cliente": cliente,
        "Placa": placa,
        "Serviço": servico,
        "Valor Final": valor_final,
        "Usuário": row["username"],
        "Data/Hora": row["data_hora"],
        "PDF": pdf_link,
        "tipo": row["tipo"],
        "dados_json": row["dados_json"]
    }

# --- Função de Economia ---
def calcular_economia(row):
    if row.get("tipo") == "cenarios":
        try:
            dados = json.loads(row["dados_json"])
        except Exception:
            dados = row["dados_json"]
        
        cenarios = dados.get("cenarios", [])
        valores = []
        for c in cenarios:
            v = c.get("Total Final (R$)")
            if isinstance(v, str):
                v = v.replace("R$", "").replace(".", "").replace(",", ".").strip()
            try:
                valores.append(float(v))
            except:
                pass
        
        if len(valores) > 1: 
            menor = min(valores)
            maior = max(valores)
            economia = maior - menor
            if economia > 0:
                return f"R${economia:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return "" 

# --- Função Gerar Excel ---
def gerar_excel_moderno(df_flat):
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    worksheet = workbook.add_worksheet("Relatório")
    
    header_format = workbook.add_format({'bold': True, 'bg_color': '#DEEAF6', 'border': 1, 'align': 'left'})
    money_format = workbook.add_format({'num_format': 'R$ #,##0.00', 'border': 1})
    normal_format = workbook.add_format({'border': 1})
    link_format = workbook.add_format({'font_color': 'blue', 'underline': 1, 'border': 1})

    headers = list(df_flat.columns)
    for col, header in enumerate(headers):
        worksheet.write(0, col, header, header_format)
        worksheet.set_column(col, col, 22)  

    for row_idx, row in df_flat.iterrows():
        for col_idx, value in enumerate(row):
            col_name = headers[col_idx]
            
            if col_name == "PDF" and value and "http" in value:
                worksheet.write_url(row_idx+1, col_idx, value, link_format, string="Baixar PDF")
            elif "R$" in str(value):
                try:
                    num_value = float(value.replace("R$", "").replace(".", "").replace(",", "."))
                    worksheet.write_number(row_idx+1, col_idx, num_value, money_format)
                except:
                    worksheet.write(row_idx+1, col_idx, value, normal_format) 
            else:
                worksheet.write(row_idx+1, col_idx, value, normal_format)
                
    workbook.close()
    output.seek(0)
    return output


# --- Definição das colunas ---
ANALISES_COLS = ["id", "username", "tipo", "data_hora", "dados_json", "pdf_path"]
REQUIRED_USER_COLUMNS = [
    "username", "password", "role", "full_name", "matricula",
    "email", "status", "accepted_terms_on", "reset_token", "reset_expires_at",
    "last_password_change", "force_password_reset"
]
TICKET_COLUMNS = ["id", "username", "full_name", "email", "assunto", "descricao", "status", "resposta", "data_criacao", "data_resposta"]
SUPERADMIN_USERNAME = st.secrets.get("SUPERADMIN_USERNAME", "lucas.sureira")


# =========================
# Page config
# =========================
try:
    st.set_page_config(
        page_title="Frotas Vamos SLA",
        page_icon=FAVICON_URL,
        layout="centered",
        initial_sidebar_state="expanded"
    )
except Exception as e:
    st.set_page_config(
        page_title="Frotas Vamos SLA",
        page_icon="🚛",
        layout="centered",
        initial_sidebar_state="expanded"
    )

load_css("estilo.css")

# =========================
# Funções de Dados (Refatoradas para Supabase)
# =========================

# --- Análises ---
@st.cache_data(ttl=60)
def load_analises():
    try:
        response = supabase.table('analises').select("*").execute()
        df = pd.DataFrame(response.data)
    except Exception as e:
        st.error(f"Erro ao carregar análises do Supabase: {e}")
        df = pd.DataFrame(columns=ANALISES_COLS)

    for col in ANALISES_COLS:
        if col not in df.columns:
            df[col] = pd.Series(dtype='object')
    
    return df[ANALISES_COLS].fillna("")

def save_analises(df):
    try:
        for col in ANALISES_COLS:
            if col not in df.columns:
                df[col] = ""
        df = df[ANALISES_COLS]
        
        supabase.table('analises').upsert(df.to_dict('records')).execute()
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Erro ao salvar análises no Supabase: {e}")

def registrar_analise(username, tipo, dados, pdf_bytes):
    novo_id = str(uuid.uuid4())
    data_hora = datetime.now(tz_brasilia).strftime("%Y-%m-%d %H:%M:%S")
    
    pdf_filename = f"{tipo}_{username}_{novo_id}_{data_hora.replace(' ','_').replace(':','-')}.pdf"
    
    try:
        supabase.storage.from_("pdfs").upload(
            path=pdf_filename,
            file=pdf_bytes.getvalue(), 
            file_options={"content-type": "application/pdf"}
        )
    except Exception as e:
        st.warning(f"Falha ao fazer upload do PDF para o Supabase Storage: {e}")
        pass
        
    if isinstance(dados, pd.DataFrame):
        dados = dados.to_dict(orient="records")
    elif isinstance(dados, pd.Series):
        dados = dados.to_dict()

    novo_registro = {
        "id": novo_id,
        "username": username,
        "tipo": tipo,
        "data_hora": data_hora,
        "dados_json": json.dumps(dados, ensure_ascii=False, default=converter_json),
        "pdf_path": pdf_filename
    }
    
    try:
        supabase.table('analises').insert(novo_registro).execute()
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Erro ao registrar análise no Supabase: {e}")

# --- Tickets ---
@st.cache_data(ttl=60)
def load_tickets():
    try:
        response = supabase.table('tickets').select("*").execute()
        df = pd.DataFrame(response.data)
    except Exception as e:
        st.error(f"Erro ao carregar tickets do Supabase: {e}")
        df = pd.DataFrame(columns=TICKET_COLUMNS)

    for col in TICKET_COLUMNS:
        if col not in df.columns:
            df[col] = pd.Series(dtype='object')
    
    return df[TICKET_COLUMNS].fillna("")

def save_tickets(df):
    try:
        for col in TICKET_COLUMNS:
            if col not in df.columns:
                df[col] = ""
        df = df[TICKET_COLUMNS]
        
        supabase.table('tickets').upsert(df.to_dict('records')).execute()
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Erro ao salvar tickets no Supabase: {e}")

# --- Usuários ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    try:
        return pwd_context.hash(password)
    except Exception:
        return hashlib.sha256(password.encode()).hexdigest()

@st.cache_data(ttl=60)
def load_user_db() -> pd.DataFrame:
    try:
        response = supabase.table('users').select("*").execute()
        df = pd.DataFrame(response.data)
    except Exception as e:
        st.error(f"Erro ao carregar usuários do Supabase: {e}")
        st.info("Tentando criar tabela de usuários inicial...")
        df = pd.DataFrame(columns=REQUIRED_USER_COLUMNS)

    for col in REQUIRED_USER_COLUMNS:
        if col not in df.columns:
            df[col] = pd.Series(dtype='object')

    if df.empty or SUPERADMIN_USERNAME not in df["username"].values:
        st.warning("Nenhum usuário encontrado, criando SuperAdmin padrão...")
        tmp_pwd = (st.secrets.get("SUPERADMIN_DEFAULT_PASSWORD", "") or "").strip()
        
        now_brasilia_str = datetime.now(tz_brasilia).strftime("%Y-%m-%d %H:%M:%S")

        admin_defaults = {
            "username": SUPERADMIN_USERNAME,
            "password": hash_password(tmp_pwd) if tmp_pwd else "",
            "role": "superadmin",
            "full_name": "Lucas Mateus Sureira",
            "matricula": "30159179",
            "email": st.secrets.get("SUPERADMIN_EMAIL", "lucas.sureira@grupovamos.com.br"),
            "status": "aprovado",
            "accepted_terms_on": "",
            "reset_token": "",
            "reset_expires_at": "",
            "last_password_change": now_brasilia_str if tmp_pwd else "",
            "force_password_reset": "" if tmp_pwd else "1",
        }
        
        try:
            supabase.table('users').insert(admin_defaults).execute()
            st.cache_data.clear()
            response = supabase.table('users').select("*").execute()
            df = pd.DataFrame(response.data)
        except Exception as e:
            st.error(f"FALHA CRÍTICA: Não foi possível criar o SuperAdmin no Supabase. {e}")
            st.stop()
            
    return df[REQUIRED_USER_COLUMNS].fillna("")

def save_user_db(df_users: pd.DataFrame):
    try:
        for col in REQUIRED_USER_COLUMNS:
            if col not in df_users.columns:
                df_users[col] = ""
        df_users = df_users[REQUIRED_USER_COLUMNS]

        for col in ['force_password_reset']:
             if col in df_users.columns:
                df_users[col] = df_users[col].astype(str)

        supabase.table('users').upsert(df_users.to_dict('records'), on_conflict="username").execute()
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Erro ao salvar usuários no Supabase: {e}")

# =========================
# Background helpers (Login)
# =========================
def show_logo_url(url: str, width: int = 140):
    st.image(url, width=width)
    st.markdown("""
        <style>
        button[title="Expandir imagem"], button[title="Expand image"], button[aria-label="Expandir imagem"], button[aria-label="Expand image"] {
            display: none !important;
        }
        </style>
        """, unsafe_allow_html=True)

# =========================
# Utilities & Password
# =========================
def get_query_params():
    try:
        return dict(st.query_params)
    except Exception:
        try:
            params = st.experimental_get_query_params()
            return {k: (v[0] if isinstance(v, list) else v) for k, v in params.items()}
        except Exception:
            return {}

def safe_rerun():
    try:
        st.experimental_rerun()
    except AttributeError:
        try:
            st.rerun()
        except Exception:
            pass
    except Exception:
        pass

def clear_all_query_params():
    try:
        st.query_params.clear()
    except AttributeError:
        try:
            st.experimental_set_query_params()
        except Exception:
            pass
    except Exception:
        pass

def get_app_base_url():
    try:
        url = (st.secrets.get("APP_BASE_URL", "") or "").strip()
    except Exception:
        url = ""
    if url.endswith("/"):
        url = url[:-1]
    return url

def is_bcrypt_hash(s: str) -> bool:
    return isinstance(s, str) and s.startswith("$2")

def verify_password(stored_hash: str, provided_password: str) -> Tuple[bool, bool]:
    if is_bcrypt_hash(stored_hash):
        try:
            ok = pwd_context.verify(provided_password, stored_hash)
            return ok, (ok and pwd_context.needs_update(stored_hash))
        except Exception:
            return False, False
    legacy = hashlib.sha256(provided_password.encode()).hexdigest()
    ok = (stored_hash == legacy)
    return ok, bool(ok)

# =========================
# Tema Autenticado
# =========================
def aplicar_estilos_authenticated():
    css = """
    <style id="app-auth-style">
    /* Esta função SÓ vai sobrescrever o fundo para as telas logadas,
       anulando o fundo de login do estilo.css */
    .stApp {
        background-image: none !important;
        background: radial-gradient(circle at 10% 10%, rgba(15,23,42,0.96) 0%, rgba(11,17,24,1) 50%) !important;
    }
    
    /* Garante que o CSS de esconder o menu seja aplicado */
    header[data-testid="stHeader"], #MainMenu, footer {
        display: none !important;
    }
    </style>
    """
    try:
        st.markdown(css, unsafe_allow_html=True)
    except Exception:
        pass

# =========================
# Política de Senha
# =========================
PASSWORD_MIN_LEN = 10
SPECIAL_CHARS = r"!@#$%^&*()_+\-=\[\]{};':\",.<>/?\\|`~"

def validate_password_policy(password: str, username: str = "", email: str = ""):
    errors = []
    if len(password) < PASSWORD_MIN_LEN:
        errors.append(f"Senha deve ter pelo menos {PASSWORD_MIN_LEN} caracteres.")
    if not re.search(r"[A-Z]", password):
        errors.append("Senha deve conter pelo menos 1 letra maiúscula.")
    if not re.search(r"[a-z]", password):
        errors.append("Senha deve conter pelo menos 1 letra minúscula.")
    if not re.search(r"[0-9]", password):
        errors.append("Senha deve conter pelo menos 1 número.")
    if not re.search(rf"[{re.escape(SPECIAL_CHARS)}]", password):
        errors.append("Senha deve conter pelo menos 1 caractere especial.")
    uname = (username or "").strip().lower()
    local_email = (email or "").split("@")[0].strip().lower()
    if uname and uname in password.lower():
        errors.append("Senha não pode conter o seu usuário.")
    if local_email and local_email in password.lower():
        errors.append("Senha não pode conter a parte local do seu e-mail.")
    return (len(errors) == 0), errors

# =========================
# Helpers de E-mail
# =========================
def smtp_available():
    host = st.secrets.get("EMAIL_HOST", "")
    user = st.secrets.get("EMAIL_USERNAME", "")
    password = st.secrets.get("EMAIL_PASSWORD", "")
    return bool(host and user and password)

def build_email_html(title: str, subtitle: str, body_lines: List[str], cta_label: str = "", cta_url: str = "", footer: str = "") -> str:
    primary = "#2563EB"
    brand = "#0d1117"
    text = "#0b1f2a"
    light = "#f6f8fa"
    button_html = ""
    if cta_label and cta_url:
        button_html = f"""
        <tr>
            <td align="center" style="padding: 28px 0 10px 0;">
                <a href="{cta_url}" style="background:{primary};color:#ffffff;text-decoration:none;font-weight:600;padding:12px 22px;border-radius:8px;display:inline-block;font-family:Segoe UI,Arial,sans-serif">
                    {cta_label}
                </a>
            </td>
        </tr>
        """
    body_html = "".join([f'<p style="margin:8px 0 8px 0">{line}</p>' for line in body_lines])
    footer_html = f'<p style="color:#6b7280;font-size:12px">{footer}</p>' if footer else ""
    return f"""<!DOCTYPE html>
<html>
    <body style="margin:0;padding:0;background:{light}">
        <table role="presentation" cellspacing="0" cellpadding="0" border="0" align="center" width="100%" style="background:{light};padding:24px 0">
            <tr>
                <td>
                    <table role="presentation" cellspacing="0" cellpadding="0" border="0" align="center" width="600" style="margin:0 auto;background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #e5e7eb">
                        <tr>
                            <td style="background:{brand};padding:18px 24px;color:#ffffff;">
                                <div style="display:flex;align-items:center;gap:12px">
                                    <span style="font-weight:700;font-size:18px;font-family:Segoe UI,Arial,sans-serif">Frotas Vamos SLA</span>
                                </div>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding:24px 24px 0 24px;color:{text};font-family:Segoe UI,Arial,sans-serif">
                                <h2 style="margin:0 0 6px 0;font-weight:700">{title}</h2>
                                <p style="margin:0 0 12px 0;color:#475569">{subtitle}</p>
                                {body_html}
                            </td>
                        </tr>
                        {button_html}
                        <tr>
                            <td style="padding:12px 24px 24px 24px;color:#334155;font-family:Segoe UI,Arial,sans-serif">
                                {footer_html}
                            </td>
                        </tr>
                    </table>
                    <div style="text-align:center;color:#94a3b8;font-size:12px;margin-top:8px;font-family:Segoe UI,Arial,sans-serif">
                        © {datetime.now().year} Vamos Locação. Todos os direitos reservados.
                    </div>
                </td>
            </tr>
        </table>
    </body>
</html>"""

def send_email(dest_email: str, subject: str, body_plain: str, body_html: Optional[str] = None) -> bool:
    host = st.secrets.get("EMAIL_HOST", "")
    port = int(st.secrets.get("EMAIL_PORT", 587) or 587)
    user = st.secrets.get("EMAIL_USERNAME", "")
    password = st.secrets.get("EMAIL_PASSWORD", "")
    use_tls = str(st.secrets.get("EMAIL_USE_TLS", "True")).lower() in ("1", "true", "yes")
    sender = st.secrets.get("EMAIL_FROM", user or "no-reply@example.com")
    if not host or not user or not password:
        st.warning("Configurações de e-mail não definidas em st.secrets. Exibindo conteúdo (teste).")
        st.code(f"Simulated email to: {dest_email}\nSubject: {subject}\n\n{body_plain}", language="text")
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = dest_email
        msg.set_content(body_plain)
        if body_html:
            msg.add_alternative(body_html, subtype="html")
        server = smtplib.SMTP(host, port, timeout=20)
        server.ehlo()
        if use_tls:
            server.starttls()
            server.ehlo()
        if user and password:
            server.login(user, password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        try:
            st.error(f"Falha ao enviar e-mail: {e}")
        except Exception:
            print("Falha ao enviar e-mail:", e)
        st.code(f"Para: {dest_email}\nAssunto: {subject}\n\n{body_plain}", language="text")
        return False

def send_reset_email(dest_email: str, reset_link: str) -> bool:
    subject = "Redefinição de senha - Frotas Vamos SLA"
    plain = f"""Olá,

Recebemos uma solicitação para redefinir sua senha no Frotas Vamos SLA.
Use o link abaixo (válido por 30 minutos):

{reset_link}

Se você não solicitou, ignore este e-mail.
"""
    html = build_email_html(
        title="Redefinição de senha",
        subtitle="Você solicitou redefinir sua senha no Frotas Vamos SLA.",
        body_lines=["Este link é válido por 30 minutos.", "Se você não solicitou, ignore este e-mail."],
        cta_label="Redefinir senha",
        cta_url=reset_link,
        footer="Este é um e-mail automático. Não responda."
    )
    return send_email(dest_email, subject, plain, html)

def send_approved_email(dest_email: str, base_url: str) -> bool:
    subject = "Conta aprovada - Frotas Vamos SLA"
    plain = f"""Olá,

Sua conta no Frotas Vamos SLA foi aprovada.
Acesse a plataforma: {base_url}

Bom trabalho!
"""
    html = build_email_html(
        title="Conta aprovada",
        subtitle="Seu acesso ao Frotas Vamos SLA foi liberado.",
        body_lines=["Você já pode acessar a plataforma com seu usuário e senha."],
        cta_label="Acessar plataforma",
        cta_url=base_url,
        footer="Em caso de dúvidas, procure o administrador do sistema."
    )
    return send_email(dest_email, subject, plain, html)

def send_invite_to_set_password(dest_email: str, reset_link: str) -> bool:
    subject = "Sua conta foi aprovada - Defina sua senha"
    plain = f"""Olá,

Sua conta no Frotas Vamos SLA foi aprovada.
Para definir sua senha inicial, use o link (válido por 30 minutos):
{reset_link}

Bom trabalho!
"""
    html = build_email_html(
        title="Defina sua senha",
        subtitle="Sua conta foi aprovada no Frotas Vamos SLA. Defina sua senha para começar a usar.",
        body_lines=["O link é válido por 30 minutos."],
        cta_label="Definir senha",
        cta_url=reset_link,
        footer="Se você não reconhece esta solicitação, ignore este e-mail."
    )
    return send_email(dest_email, subject, plain, html)

# =========================
# Lógica de Senha
# =========================
def is_password_expired(row) -> bool:
    try:
        last = row.get("last_password_change", "")
        if not last:
            return True
        last_dt = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
        expiry_days = int(st.secrets.get("PASSWORD_EXPIRY_DAYS", 90))
        
        last_dt_aware = tz_brasilia.localize(last_dt)
        now_aware = datetime.now(tz_brasilia)
        
        return now_aware > (last_dt_aware + timedelta(days=expiry_days))
    except Exception:
        return True
        
# =========================
# Base / calculations / PDFs (Excel)
# =========================
@st.cache_data
def carregar_base() -> Optional[pd.DataFrame]:
    try:
        return pd.read_excel(resource_path("Base De Clientes Faturamento.xlsx"))
    except Exception:
        return None

def formatar_moeda(valor):
    return f"R${valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def moeda_para_float(valor_str):
    if isinstance(valor_str, (int, float)):
        return float(valor_str)
    if isinstance(valor_str, str):
        valor_str = valor_str.replace("R$", "").replace(".", "").replace(",", ".").strip()
        try:
            return float(valor_str)
        except:
            return 0.0
    return 0.0

def calcular_cenario_comparativo(cliente, placa, entrada, saida, feriados, servico, pecas, mensalidade):
    dias = np.busday_count(entrada.strftime('%Y-%m-%d'), (saida + timedelta(days=1)).strftime('%Y-%m-%d'))
    dias_uteis = max(dias - int(feriados or 0), 0)
    sla_dict = {"Preventiva – 2 dias úteis": 2, "Corretiva – 3 dias úteis": 3,
                "Preventiva + Corretiva – 5 dias úteis": 5, "Motor – 15 dias úteis": 15}
    sla_dias = sla_dict.get(servico, 0)
    excedente = max(0, dias_uteis - sla_dias)
    desconto = (mensalidade / 30) * excedente if excedente > 0 else 0
    total_pecas = sum(float(p.get("valor", 0) or 0) for p in (pecas or []))
    total_final = (mensalidade - desconto) + total_pecas
    return {
        "Cliente": cliente, "Placa": placa,
        "Data Entrada": entrada.strftime("%d/%m/%Y"),
        "Data Saída": saida.strftime("%d/%m/%Y"),
        "Serviço": servico, "Dias Úteis": dias_uteis,
        "SLA (dias)": sla_dias, "Excedente": excedente,
        "Mensalidade": formatar_moeda(mensalidade),
        "Desconto": formatar_moeda(round(desconto, 2)),
        "Peças (R$)": formatar_moeda(round(total_pecas, 2)),
        "Total Final (R$)": formatar_moeda(round(total_final, 2)),
        "Detalhe Peças": pecas or []
    }

def gerar_pdf_comparativo(df_cenarios, melhor_cenario):
    if df_cenarios is None or df_cenarios.empty:
        return BytesIO()
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=30, rightMargin=30, topMargin=30, bottomMargin=30)
    elementos, styles = [], getSampleStyleSheet()
    styles['Normal'].leading = 14
    elementos.append(Paragraph("🚛 Relatório Comparativo de Cenários SLA", styles['Title']))
    elementos.append(Spacer(1, 24))
    for i, row in df_cenarios.iterrows():
        elementos.append(Paragraph(f"<b>Cenário {i+1}</b>", styles['Heading2']))
        for col, valor in row.items():
            if col != "Detalhe Peças":
                elementos.append(Paragraph(f"<b>{col}:</b> {valor}", styles['Normal']))
        if isinstance(row.get("Detalhe Peças", []), list) and row["Detalhe Peças"]:
            elementos.append(Paragraph("<b>Detalhe de Peças:</b>", styles['Normal']))
            for peca in row["Detalhe Peças"]:
                elementos.append(Paragraph(f"- {peca.get('nome','')}: {formatar_moeda(peca.get('valor',0))}", styles['Normal']))
        elementos.append(Spacer(1, 12))
        elementos.append(Paragraph("─" * 90, styles['Normal']))
        elementos.append(Spacer(1, 12))
    texto_melhor = (f"<b>🏆 Melhor Cenário (Menor Custo Final)</b><br/>"
                    f"Serviço: {melhor_cenario.get('Serviço','')}<br/>"
                    f"Placa: {melhor_cenario.get('Placa','')}<br/>"
                    f"<b>Total Final: {melhor_cenario.get('Total Final (R$)','')}</b>")
    elementos.append(Spacer(1, 12))
    elementos.append(Paragraph(texto_melhor, styles['Heading2']))
    doc.build(elementos)
    buffer.seek(0)
    return buffer

def calcular_sla_simples(data_entrada, data_saida, prazo_sla, valor_mensalidade, feriados):
    def to_date(obj):
        if hasattr(obj, "date"):
            return obj.date()
        return obj
    dias = np.busday_count(np.datetime64(to_date(data_entrada)), np.datetime64(to_date(data_saida + timedelta(days=1))))
    dias -= int(feriados or 0)
    dias = max(dias, 0)
    if dias <= prazo_sla:
        status = "Dentro do prazo"; desconto = 0; dias_excedente = 0
    else:
        status = "Fora do prazo"
        dias_excedente = dias - prazo_sla
        desconto = (valor_mensalidade / 30) * dias_excedente
    return dias, status, desconto, dias_excedente

def gerar_pdf_sla_simples(cliente, placa, tipo_servico, dias_uteis_manut, prazo_sla, dias_excedente, valor_mensalidade, desconto):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    largura, altura = letter
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, altura - 50, "Resultado SLA - Vamos Locação")
    c.setFont("Helvetica", 12)
    y = altura - 80
    text_lines = [
        f"Cliente: {cliente}",
        f"Placa: {placa}",
        f"Tipo de serviço: {tipo_servico}",
        f"Dias úteis da manutenção: {dias_uteis_manut} dias",
        f"Prazo SLA: {prazo_sla} dias",
        f"Dias excedido de SLA: {dias_excedente} dias",
        f"Valor Mensalidade: {formatar_moeda(valor_mensalidade)}",
        f"Valor do desconto: {formatar_moeda(desconto)}"
    ]
    for line in text_lines:
        c.drawString(50, y, line); y -= 20
    c.showPage(); c.save(); buffer.seek(0); return buffer

# =========================
# Navigation helpers & sidebar
# =========================
def ir_para_home(): st.session_state.tela = "home"
def ir_para_calc_comparativa(): st.session_state.tela = "calc_comparativa"
def ir_para_calc_simples(): st.session_state.tela = "calc_simples"
def ir_para_admin(): st.session_state.tela = "admin_users"
def ir_para_login(): st.session_state.tela = "login"
def ir_para_register(): st.session_state.tela = "register"
def ir_para_forgot(): st.session_state.tela = "forgot_password"
def ir_para_reset(): st.session_state.tela = "reset_password"
def ir_para_force_change(): st.session_state.tela = "force_change_password"
def ir_para_relatorio_analises(): st.session_state.tela = "relatorio_analises"
def ir_para_terms(): st.session_state.tela = "terms_consent"
def ir_para_dashboard(): st.session_state.tela = "dashboard"


def limpar_dados_comparativos():
    for key in ["cenarios", "pecas_atuais", "mostrar_comparativo"]:
        if key in st.session_state: del st.session_state[key]

def limpar_dados_simples():
    for key in ["resultado_sla", "pesquisa_cliente"]:
        if key in st.session_state: del st.session_state[key]

def logout():
    st.session_state['__do_logout'] = True

def user_is_admin():
    return st.session_state.get("role") in ("admin", "superadmin")

def user_is_superadmin():
    return st.session_state.get("username") == SUPERADMIN_USERNAME or st.session_state.get("role") == "superadmin"

# --- renderizar_sidebar (ATUALIZADO) ---
def renderizar_sidebar():
    with st.sidebar:
        st.markdown("<div style='text-align:center;padding-top:8px'>", unsafe_allow_html=True)
        try:
            show_logo_url(LOGO_URL_SIDEBAR, width=100)
        except Exception as e:
            pass
        st.markdown("</div>", unsafe_allow_html=True)

        st.header("Menu de Navegação")
        
        st.button("🏠 Voltar para Home", on_click=ir_para_home, use_container_width=True)
        
        if st.session_state.tela in ("calc_comparativa", "calc_simples"):
            st.button("🔄 Limpar Cálculo", on_click=limpar_dados_comparativos, use_container_width=True)
        
        st.button("💬 Abrir Ticket", on_click=lambda: st.session_state.update({"tela": "tickets"}), use_container_width=True)

        if user_is_admin():
            st.button("📊 Dashboard de Análises", on_click=ir_para_dashboard, use_container_width=True)
            st.button("👤 Gerenciar Usuários", on_click=ir_para_admin, use_container_width=True)
            
        if user_is_admin() or user_is_superadmin():
            st.button("📑 Relatório de Análises", on_click=ir_para_relatorio_analises, use_container_width=True)
            
        if user_is_superadmin():
            st.button("📋 Gerenciar Tickets", on_click=lambda: st.session_state.update({"tela": "admin_tickets"}), use_container_width=True)

        st.button("🚪 Sair (Logout)", on_click=logout, type="secondary", use_container_width=True)
# --- FIM DA ATUALIZAÇÃO ---

# =========================
# Initial state & routing
# =========================
if "tela" not in st.session_state:
    st.session_state.tela = "login"

qp = get_query_params()
incoming_token = qp.get("reset_token") or qp.get("token") or ""
if incoming_token and not st.session_state.get("ignore_reset_qp"):
    st.session_state.incoming_reset_token = incoming_token
    st.session_state.tela = "reset_password"
    
if st.session_state.get('__do_logout'):
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.session_state.tela = "login"
    st.session_state['__do_logout'] = False
    safe_rerun()
    
# =========================
# SCREENS
# =========================
if st.session_state.tela == "login":
    # 'estilo.css' (carregado no topo) agora controla 100% o fundo do login.
    
    st.markdown("""
    <style id="login-card-safe">
    section.main > div.block-container { max-width: 920px !important; margin: 0 auto !important; padding-top: 0 !important; padding-bottom: 0 !important; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
    .login-wrapper { width:100%; max-width:920px; margin:0 auto; box-sizing:border-box; display:flex; align-items:center; justify-content:center; padding:24px 0; }
    .brand-title { text-align:center; font-weight:700; font-size:22px; color:#E5E7EB; margin-bottom:6px; }
    .brand-subtitle { text-align:center; color: rgba(255,255,255,0.78); font-size:13px; margin-bottom:14px; }
    </style>
    """, unsafe_allow_html=True)
    
    st.markdown('<div class="login-wrapper">', unsafe_allow_html=True)
    st.markdown('<div class="login-card">', unsafe_allow_html=True) 
    
    st.markdown("<div style='text-align: center; margin-bottom: 12px;'>", unsafe_allow_html=True)
    show_logo_url(LOGO_URL_LOGIN, width=140)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='brand-title'>Frotas Vamos SLA</div>", unsafe_allow_html=True)
    st.markdown("<div class='brand-subtitle'>| Soluções inteligentes para frotas |</div>", unsafe_allow_html=True)

    with st.form("login_form"):
        username = st.text_input("Usuário", placeholder="Usuário", label_visibility="collapsed")
        password = st.text_input("Senha", type="password", placeholder="Senha", label_visibility="collapsed")
        submit_login = st.form_submit_button("Login", use_container_width=True)

    col1, col2, col3, col4, col5 = st.columns([1, 2, 2, 2, 1])
    with col2:
        if st.button("Sign up"):
            ir_para_register(); safe_rerun()
    with col4:
        if st.button("Reset Password"):
            ir_para_forgot(); safe_rerun()

    st.markdown("</div>", unsafe_allow_html=True) # Fecha login-card
    st.markdown("</div>", unsafe_allow_html=True) # Fecha login-wrapper

    if submit_login:
        df_users = load_user_db()
        user_data = df_users[df_users["username"] == username]
        if user_data.empty:
            st.error("❌ Usuário ou senha incorretos.")
        else:
            row = user_data.iloc[0]
            valid, needs_up = verify_password(row["password"], password)
            if not valid:
                st.error("❌ Usuário ou senha incorretos.")
            else:
                try:
                    if needs_up:
                        idx = df_users.index[df_users["username"] == username][0]
                        df_users.loc[idx, "password"] = hash_password(password)
                        df_users.loc[idx, "last_password_change"] = datetime.now(tz_brasilia).strftime("%Y-%m-%d %H:%M:%S")
                        save_user_db(df_users)
                except Exception:
                    pass

                if row.get("status", "") != "aprovado":
                    st.warning("⏳ Seu cadastro ainda está pendente de aprovação pelo administrador.")
                else:
                    st.session_state.logado = True
                    st.session_state.username = row["username"]
                    st.session_state.role = row.get("role", "user")
                    st.session_state.email = row.get("email", "")
                    st.session_state.full_name = row.get("full_name", "")
                    if not str(row.get("accepted_terms_on", "")).strip():
                        st.session_state.tela = "terms_consent"
                    elif is_password_expired(row) or str(row.get("force_password_reset", "")).strip() not in ["", "False", "0"]:
                        st.session_state.tela = "force_change_password"
                    else:
                        st.session_state.tela = "home"
                    safe_rerun()

# ---------------------------
# Register
# ---------------------------
elif st.session_state.tela == "register":
    aplicar_estilos_authenticated()
    st.markdown("<div class='main-container'>", unsafe_allow_html=True)
    st.title("🆕 Sign up")
    st.info("Se a sua empresa já realizou um pré-cadastro, informe seu e-mail para pré-preencher os dados.")
    if "register_prefill" not in st.session_state:
        st.session_state.register_prefill = None
    with st.form("lookup_email_form"):
        lookup_email = st.text_input("E-mail corporativo para localizar pré-cadastro")
        lookup_submit = st.form_submit_button("Buscar pré-cadastro")
    if lookup_submit and lookup_email.strip():
        df = load_user_db()
        rows = df[df["email"].str.strip().str.lower() == lookup_email.strip().lower()]
        if rows.empty:
            st.warning("Nenhum pré-cadastro encontrado para este e-mail. Você poderá preencher os dados normally.")
            st.session_state.register_prefill = None
        else:
            r = rows.iloc[0].to_dict()
            st.session_state.register_prefill = r
            st.success("Pré-cadastro encontrado! Os campos abaixo foram preenchidos automaticamente.")
    pre = st.session_state.register_prefill
    lock_username = bool(pre and pre.get("username"))
    lock_fullname = bool(pre and pre.get("full_name"))
    lock_matricula = bool(pre and pre.get("matricula"))
    lock_email = bool(pre and pre.get("email"))
    with st.form("register_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        username = col1.text_input("Usuário (login)", value=(pre.get("username") if pre else ""), disabled=lock_username)
        full_name = col2.text_input("Nome completo", value=(pre.get("full_name") if pre else ""), disabled=lock_fullname)
        col3, col4 = st.columns(2)
        matricula = col3.text_input("Matrícula", value=(pre.get("matricula") if pre else ""), disabled=lock_matricula)
        email = col4.text_input("E-mail corporativo", value=(pre.get("email") if pre else lookup_email or ""), disabled=lock_email)
        col5, col6 = st.columns(2)
        password = col5.text_input("Senha", type="password", help="Mín 10, com maiúscula, minúscula, número e especial.")
        password2 = col6.text_input("Confirmar senha", type="password")
        submit_reg = st.form_submit_button("Enviar cadastro", type="primary", use_container_width=True)
    st.button("⬅️ Voltar ao login", on_click=ir_para_login)
    if submit_reg:
        df = load_user_db()
        uname = (username or (pre.get("username") if pre else "")).strip()
        fname = (full_name or (pre.get("full_name") if pre else "")).strip()
        mail = (email or (pre.get("email") if pre else "")).strip()
        mat = (matricula or (pre.get("matricula") if pre else "")).strip()

        if not all([uname, fname, mail, password.strip(), password2.strip()]):
            st.error("Preencha todos os campos obrigatórios.")
        elif password != password2:
            st.error("As senhas não conferem.")
        else:
            valid, errs = validate_password_policy(password, username=uname, email=mail)
            if not valid:
                st.error("Regras de senha não atendidas:\n- " + "\n- ".join(errs))
            else:
                idxs = df.index[df["email"].str.strip().str.lower() == mail.lower()]
                if len(idxs) > 0:
                    idx = idxs[0]
                    if not df.loc[idx, "username"]:
                        if (uname in df["username"].values) and (df.loc[idx, "username"] != uname):
                            st.error("Nome de usuário já existe."); st.stop()
                        df.loc[idx, "username"] = uname
                    if not df.loc[idx, "full_name"]: df.loc[idx, "full_name"] = fname
                    if not df.loc[idx, "matricula"]: df.loc[idx, "matricula"] = mat
                    df.loc[idx, "password"] = hash_password(password)
                    if df.loc[idx, "status"] == "": df.loc[idx, "status"] = "pendente"
                    df.loc[idx, "last_password_change"] = datetime.now(tz_brasilia).strftime("%Y-%m-%d %H:%M:%S")
                    df.loc[idx, "force_password_reset"] = ""
                    save_user_db(df)
                    st.success("Cadastro atualizado! Aguarde aprovação (se pendente).")
                else:
                    if uname in df["username"].values:
                        st.error("Nome de usuário já existe."); st.stop()
                    
                    new_user = {col: "" for col in REQUIRED_USER_COLUMNS}
                    new_user.update({
                        "username": uname,
                        "password": hash_password(password),
                        "role": "user",
                        "full_name": fname,
                        "matricula": mat,
                        "email": mail,
                        "status": "pendente",
                        "last_password_change": datetime.now(tz_brasilia).strftime("%Y-%m-%d %H:%M:%S"),
                        "force_password_reset": ""
                    })
                    try:
                        supabase.table('users').insert(new_user).execute()
                        st.cache_data.clear()
                        st.success("✅ Cadastro enviado! Aguarde aprovação.")
                    except Exception as e:
                        st.error(f"Erro ao salvar novo usuário: {e}")
                    
    st.markdown("</div>", unsafe_allow_html=True)


# =========================
# Screens: Forgot/Reset/Force/Terms
# =========================
elif st.session_state.tela == "forgot_password":
    aplicar_estilos_authenticated()
    st.markdown("<div class='main-container'>", unsafe_allow_html=True)
    st.title("🔐 Reset Password")
    st.write("Informe seu e-mail cadastrado para enviar um link de redefinição de senha (válido por 30 minutos).")
    email = st.text_input("E-mail")
    colb1, colb2 = st.columns(2)
    enviar = colb1.button("Enviar link", type="primary", use_container_width=True)
    if colb2.button("⬅️ Voltar ao login", use_container_width=True):
        ir_para_login(); safe_rerun()
    if enviar and email.strip():
        df = load_user_db()
        user_idx = df.index[df["email"].str.strip().str.lower() == email.strip().lower()]
        if len(user_idx) == 0:
            st.error("E-mail não encontrado.")
        else:
            idx = user_idx[0]
            if df.loc[idx, "status"] != "aprovado":
                st.warning("Seu cadastro ainda não foi aprovado pelo administrador.")
            else:
                token = secrets.token_urlsafe(32)
                expires = (datetime.now(tz_brasilia) + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
                df.loc[idx, "reset_token"] = token
                df.loc[idx, "reset_expires_at"] = expires
                save_user_db(df)
                base_url = get_app_base_url() or "https://SEU_DOMINIO"
                reset_link = f"{base_url}?reset_token={token}"
                if send_reset_email(email.strip(), reset_link):
                    st.success("Enviamos um link para seu e-mail. Verifique sua caixa de entrada (e o SPAM).")
    st.markdown("</div>", unsafe_allow_html=True)


elif st.session_state.tela == "reset_password":
    aplicar_estilos_authenticated()
    st.markdown("<div class='main-container'>", unsafe_allow_html=True)
    st.title("🔁 Redefinir senha")
    token = st.session_state.get("incoming_reset_token", "")
    token = st.text_input("Token de redefinição (se veio por link, já estará preenchido)", value=token)
    colp1, colp2 = st.columns(2)
    new_pass = colp1.text_input("Nova senha", type="password", help="Mín 10, com maiúscula, minúscula, número e especial.")
    new_pass2 = colp2.text_input("Confirmar nova senha", type="password")
    colb1, colb2 = st.columns(2)
    confirmar = colb1.button("Redefinir senha", type="primary", use_container_width=True)
    voltar = colb2.button("⬅️ Voltar ao login", use_container_width=True)
    if voltar:
        st.session_state.ignore_reset_qp = True
        st.session_state.incoming_reset_token = ""
        clear_all_query_params()
        ir_para_login()
        safe_rerun()
    if confirmar:
        if not token.strip():
            st.error("Token é obrigatório.")
        elif not new_pass or not new_pass2:
            st.error("Informe e confirme a nova senha.")
        elif new_pass != new_pass2:
            st.error("As senhas não conferem.")
        else:
            df = load_user_db()
            rows = df[df["reset_token"] == token]
            if rows.empty:
                st.error("Token inválido.")
            else:
                idx = rows.index[0]
                try:
                    exp = datetime.strptime(df.loc[idx, "reset_expires_at"], "%Y-%m-%d %H:%M:%S")
                    exp_aware = tz_brasilia.localize(exp)
                    now_aware = datetime.now(tz_brasilia)
                except Exception:
                    exp_aware = datetime.now(tz_brasilia) - timedelta(minutes=1)
                    now_aware = datetime.now(tz_brasilia)
                    
                if now_aware > exp_aware:
                    st.error("Token expirado. Solicite novamente.")
                else:
                    username = df.loc[idx, "username"]
                    email = df.loc[idx, "email"]
                    ok, errs = validate_password_policy(new_pass, username=username, email=email)
                    if not ok:
                        st.error("Regras de senha não atendidas:\n- " + "\n- ".join(errs)); st.stop()
                    _same, _ = verify_password(df.loc[idx, "password"], new_pass)
                    if _same:
                        st.error("A nova senha não pode ser igual à senha atual."); st.stop()
                    df.loc[idx, "password"] = hash_password(new_pass)
                    df.loc[idx, "reset_token"] = ""
                    df.loc[idx, "reset_expires_at"] = ""
                    df.loc[idx, "last_password_change"] = datetime.now(tz_brasilia).strftime("%Y-%m-%d %H:%M:%S")
                    df.loc[idx, "force_password_reset"] = ""
                    save_user_db(df)
                    st.success("Senha redefinida com sucesso! Faça login novamente.")
                    if st.button("Ir para login", type="primary"):
                        st.session_state.ignore_reset_qp = True
                        st.session_state.incoming_reset_token = ""
                        clear_all_query_params()
                        ir_para_login()
                        safe_rerun()
    st.markdown("</div>", unsafe_allow_html=True)


elif st.session_state.tela == "force_change_password":
    aplicar_estilos_authenticated()
    st.markdown("<div class='main-container'>", unsafe_allow_html=True)
    st.title("🔒 Alteração obrigatória de senha")
    st.warning("Sua senha expirou ou foi marcada para alteração. Defina uma nova senha para continuar.")
    col1, col2 = st.columns(2)
    new_pass = col1.text_input("Nova senha", type="password", help="Mín 10, com maiúscula, minúscula, número e especial.")
    new_pass2 = col2.text_input("Confirmar nova senha", type="password")
    if st.button("Atualizar senha", type="primary"):
        df = load_user_db()
        uname = st.session_state.get("username", "")
        rows = df[df["username"] == uname]
        if rows.empty:
            st.error("Sessão inválida. Faça login novamente.")
        else:
            idx = rows.index[0]
            email = df.loc[idx, "email"]
            if not new_pass or not new_pass2:
                st.error("Preencha os campos de senha."); st.stop()
            if new_pass != new_pass2:
                st.error("As senhas não conferem."); st.stop()
            ok, errs = validate_password_policy(new_pass, username=uname, email=email)
            if not ok:
                st.error("Regras de senha não atendidas:\n- " + "\n- ".join(errs)); st.stop()
            same, _ = verify_password(df.loc[idx, "password"], new_pass)
            if same:
                st.error("A nova senha não pode ser igual à senha atual."); st.stop()
            df.loc[idx, "password"] = hash_password(new_pass)
            df.loc[idx, "last_password_change"] = datetime.now(tz_brasilia).strftime("%Y-%m-%d %H:%M:%S")
            df.loc[idx, "force_password_reset"] = ""
            save_user_db(df)
            st.success("Senha atualizada com sucesso.")
            if not str(df.loc[idx, "accepted_terms_on"]).strip():
                st.session_state.tela = "terms_consent"
            else:
                st.session_state.tela = "home"
            safe_rerun()
    st.markdown("</div>", unsafe_allow_html=True)


# =========================
# Terms / LGPD (full)
# =========================
elif st.session_state.tela == "terms_consent":
    aplicar_estilos_authenticated()
    st.markdown("<div class='main-container'>", unsafe_allow_html=True)
    st.title("Termos e Condições de Uso e Política de Privacidade (LGPD)")
    st.info("Para seu primeiro acesso, é necessário ler e aceitar os termos de uso e a política de privacidade desta plataforma.")
    terms_html = dedent("""
    <div class="terms-box" style="color:#fff;font-family:Segoe UI,Arial,sans-serif;">
        <p><b>Última atualização:</b> 28 de Setembro de 2025</p>
        <h3>1. Finalidade da Ferramenta</h3>
        <p>Esta plataforma é um sistema interno para simulação e referência de cálculos de
        Service Level Agreement (SLA) e apoio operacional. Os resultados são estimativas
        destinadas ao uso profissional e não substituem documentos contratuais, fiscais
        ou aprovados formalmente pela empresa.</p>
        <h3>2. Base Legal e Conformidade com a LGPD</h3>
        <p>O tratamento de dados pessoais nesta plataforma observa a Lei nº 13.709/2018
        (Lei Geral de Proteção de Dados Pessoais – LGPD), adotando medidas técnicas e
        administrativas para proteger os dados contra acessos não autorizados e situações
        acidentais ou ilícitas de destruição, perda, alteração, comunicação ou difusão.</p>
        <h3>3. Dados Coletados e Tratados</h3>
        <ul>
            <li>Dados de autenticação: usuário (login), senha (armazenada de forma irreversível via hash), perfil de acesso (user/admin).</li>
            <li>Dados cadastrais: nome completo, matrícula, e-mail corporativo.</li>
            <li>Dados operacionais: clientes, placas, valores de mensalidade e informações utilizadas nos cálculos de SLA.</li>
            <li>Registros de aceite: data/hora do aceite dos termos.</li>
        </ul>
        <h3>4. Finalidades do Tratamento</h3>
        <ul>
            <li>Autenticação e autorização de acesso à plataforma.</li>
            <li>Execução dos cálculos de SLA e geração de relatórios.</li>
            <li>Gestão de usuários (aprovação de cadastro por administradores).</li>
            <li>Comunicações operacionais, como e-mail de redefinição de senha e avisos de aprovação de conta.</li>
        </ul>
        <h3>5. Compartilhamento e Acesso</h3>
        <p>Os dados processados são de uso interno e não são compartilhados com terceiros,
        exceto quando necessários para cumprimento de obrigações legais ou ordem de
        autoridades competentes.</p>
        <h3>6. Segurança da Informação</h3>
        <ul>
            <li>Senhas armazenadas com algoritmo de hash (não reversível).</li>
            <li>Acesso restrito a usuários autorizados e administradores.</li>
            <li>Envio de e-mails mediante configurações autenticadas de SMTP corporativo.</li>
        </ul>
        <h3>7. Direitos dos Titulares</h3>
        <p>Nos termos da LGPD, o titular possui direitos como confirmação de tratamento,
        acesso, correção, anonimização, bloqueio, eliminação de dados desnecessários,
        portabilidade (quando aplicável) e informação sobre compartilhamentos.</p>
        <h3>8. Responsabilidades do Usuário</h3>
        <ul>
            <li>Manter a confidencialidade de suas credenciais de acesso.</li>
            <li>Utilizar a plataforma apenas para fins profissionais internos.</li>
            <li>Respeitar as políticas internas e as legislações aplicáveis.</li>
        </ul>
        <h3>9. Retenção e Eliminação</h3>
        <p>Os dados são mantidos pelo período necessário ao atendimento das finalidades
        acima e das políticas internas. Após esse período, poderão ser eliminados ou
        anonimizados, salvo obrigações legais de retenção.</p>
        <h3>10. Alterações dos Termos</h3>
        <p>Estes termos podem ser atualizados a qualquer tempo, mediante publicação
        de nova versão na própria plataforma. Recomenda-se a revisão periódica.</p>
        <h3>11. Contato</h3>
        <p>Em caso de dúvidas sobre estes Termos ou sobre o tratamento de dados pessoais,
        procure o time responsável pela ferramenta ou o canal corporativo de Privacidade/DPD.</p>
    </div>
    """)
    components_html(terms_html, height=520, scrolling=True)
    st.markdown("---")
    consent = st.checkbox("Eu li e concordo com os Termos e Condições.")
    if st.button("Continuar", disabled=not consent, type="primary"):
        df_users = load_user_db()
        now = datetime.now(tz_brasilia).strftime('%Y-%m-%d %H:%M:%S')
        username = st.session_state.get("username", "")
        if username:
            user_index = df_users.index[df_users['username'] == username]
            if len(user_index) > 0:
                df_users.loc[user_index[0], 'accepted_terms_on'] = now
                save_user_db(df_users)
        row = df_users[df_users['username'] == username].iloc[0]
        if is_password_expired(row) or str(row.get("force_password_reset", "")).strip() not in ["", "False", "0"]:
            st.session_state.tela = "force_change_password"
        else:
            st.session_state.tela = "home"
        safe_rerun()
    st.markdown("</div>", unsafe_allow_html=True)


# =========================
# Área Autenticada
# =========================
else:
    if not st.session_state.get("logado"):
        ir_para_login()
        safe_rerun()
        st.stop()
        
    aplicar_estilos_authenticated() # Aplica o fundo de gradiente
    renderizar_sidebar()
    st.markdown("<div class='main-container'>", unsafe_allow_html=True)

    if st.session_state.tela == "home":
        st.title("🏠 Home")
        st.write(f"### Bem-vindo, {st.session_state.get('full_name', st.session_state.get('username',''))}!")
        st.markdown("---")
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("📊 Análise de Cenários")
            st.write("Calcule e compare múltiplos cenários para encontrar a opção com o menor custo final.")
            st.button("Acessar Análise de Cenários", on_click=ir_para_calc_comparativa, use_container_width=True)
        with col2:
            st.subheader("🖩 SLA Mensal")
            st.write("Calcule rapidamente o desconto de SLA para um único serviço ou veículo.")
            st.button("Acessar SLA Mensal", on_click=ir_para_calc_simples, use_container_width=True)

    # --- 💡 NOVA PÁGINA: DASHBOARD 💡 ---
    elif st.session_state.tela == "dashboard":
        if not user_is_admin():
            st.error("Acesso negado."); ir_para_home(); safe_rerun(); st.stop()
            
        st.title("📊 Dashboard de Análises")
        
        df = load_analises()
        
        # Prepara os dados para os gráficos
        if df.empty or 'data_hora' not in df.columns or df['data_hora'].isnull().all():
            st.info("Nenhum dado de análise encontrado para exibir o dashboard.")
        else:
            df['data_hora_dt'] = pd.to_datetime(df['data_hora'], errors='coerce')
            df = df.dropna(subset=['data_hora_dt'])
            
            if df.empty:
                st.info("Nenhum dado de análise com data válida encontrado.")
            else:
                df['mes_ano'] = df['data_hora_dt'].dt.strftime('%Y-%m')
                df['ano'] = df['data_hora_dt'].dt.year
                df['mes'] = df['data_hora_dt'].dt.month
                
                # Calcula a economia ANTES de filtrar
                df['economia_val'] = df.apply(
                    lambda row: float(calcular_economia(row).replace("R$", "").replace(".", "").replace(",", ".")) if row['tipo'] == 'cenarios' and calcular_economia(row) else 0,
                    axis=1
                )
                
                # --- Filtros ---
                st.markdown("### Filtros")
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    anos_disponiveis = sorted(df['ano'].unique(), reverse=True)
                    opcoes_ano = ["Todos"] + [int(a) for a in anos_disponiveis]
                    ano_sel = st.selectbox("Filtrar por ano:", opcoes_ano)
                
                with col2:
                    meses_map = {
                        'Janeiro': 1, 'Fevereiro': 2, 'Março': 3, 'Abril': 4, 'Maio': 5, 'Junho': 6,
                        'Julho': 7, 'Agosto': 8, 'Setembro': 9, 'Outubro': 10, 'Novembro': 11, 'Dezembro': 12
                    }
                    opcoes_mes = ["Todos"] + list(meses_map.keys())
                    mes_sel = st.selectbox("Filtrar por mês:", opcoes_mes)
                
                with col3:
                    opcoes_tipo = ["Todos", "cenarios", "sla_mensal"]
                    tipo_sel = st.selectbox("Tipo de análise:", opcoes_tipo)

                # Aplicar filtros
                df_filtrado = df.copy()
                if ano_sel != "Todos":
                    df_filtrado = df_filtrado[df_filtrado['ano'] == ano_sel]
                if mes_sel != "Todos":
                    df_filtrado = df_filtrado[df_filtrado['mes'] == meses_map[mes_sel]]
                if tipo_sel != "Todos":
                    df_filtrado = df_filtrado[df_filtrado['tipo'] == tipo_sel]

                st.markdown("---")
                
                # --- KPIs (Métricas) ---
                st.subheader("Resumo do Período Selecionado")
                total_economia = df_filtrado['economia_val'].sum()
                total_analises = len(df_filtrado)
                total_cenarios = len(df_filtrado[df_filtrado['tipo'] == 'cenarios'])
                total_sla = len(df_filtrado[df_filtrado['tipo'] == 'sla_mensal'])

                col1, col2, col3 = st.columns(3)
                col1.metric("Economia Gerada", f"R$ {total_economia:,.2f}")
                col2.metric("Análises de 'Cenários'", total_cenarios)
                col3.metric("Análises 'SLA Mensal'", total_sla)
                
                st.markdown("---")
                
                # --- Gráficos ---
                st.subheader("Visualizações")

                col1, col2 = st.columns(2)
                
                with col1:
                    st.write("Análises por Tipo")
                    if not df_filtrado.empty:
                        tipo_counts = df_filtrado['tipo'].value_counts().reset_index()
                        tipo_counts.columns = ['tipo', 'contagem']
                        st.bar_chart(tipo_counts, x='tipo', y='contagem')
                    else:
                        st.info("Nenhum dado para este período.")
                
                with col2:
                    st.write("Análises por Usuário")
                    if not df_filtrado.empty:
                        user_counts = df_filtrado['username'].value_counts().reset_index()
                        user_counts.columns = ['username', 'contagem']
                        st.bar_chart(user_counts, x='username', y='contagem')
                    else:
                        st.info("Nenhum dado para este período.")

                # Gráficos que só aparecem se o filtro for "Todos os Meses/Anos"
                if mes_sel == "Todos" and ano_sel == "Todos":
                    st.markdown("---")
                    st.subheader("Análise Histórica (Todos os Períodos)")
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.write("Total de Análises por Mês")
                        mes_counts = df.groupby('mes_ano').size().reset_index(name='Total')
                        mes_counts = mes_counts.sort_values(by='mes_ano')
                        st.line_chart(mes_counts, x='mes_ano', y='Total')
                    
                    with col2:
                        st.write("Economia Gerada por Mês")
                        economia_mes = df[df['economia_val'] > 0].groupby('mes_ano')['economia_val'].sum().reset_index(name='Economia (R$)')
                        economia_mes = economia_mes.sort_values(by='mes_ano')
                        st.bar_chart(economia_mes, x='mes_ano', y='Economia (R$)')

    # --- FIM DA NOVA PÁGINA ---

    elif st.session_state.tela == "admin_users":
        if not user_is_admin(): st.error("Acesso negado."); ir_para_home(); safe_rerun(); st.stop()
        st.title("👤 Gerenciamento de Usuários")
        df_users = load_user_db()

        with st.expander("✉️ Testar envio de e-mail (SMTP)", expanded=False):
            st.write("Use este teste para validar rapidamente as credenciais de e-mail em st.secrets.")
            test_to = st.text_input("Enviar e-mail de teste para:")
            if st.button("Enviar e-mail de teste"):
                if not test_to.strip():
                    st.warning("Informe um e-mail de destino.")
                else:
                    ok = send_email(
                        test_to.strip(),
                        "Teste SMTP - Frotas Vamos SLA",
                        "E-mail de teste enviado pelo aplicativo.",
                        build_email_html(
                            title="Teste de e-mail",
                            subtitle="Este é um e-mail de teste do Frotas Vamos SLA.",
                            body_lines=["Se você recebeu, o SMTP está funcionando corretamente."],
                            cta_label="Abrir plataforma",
                            cta_url=get_app_base_url() or "https://streamlit.io"
                        )
                    )
                    if ok:
                        st.success("E-mail de teste enviado com sucesso!")
            st.write("Status configurações:")
            st.write(f"- APP_BASE_URL: {'OK' if get_app_base_url() else 'NÃO CONFIGURADO'}")
            st.write(f"- SMTP: {'OK' if smtp_available() else 'NÃO CONFIGURADO'}")

        st.markdown("---")

        pendentes = df_users[df_users["status"] == "pendente"]
        st.subheader("Cadastros pendentes")
        if pendentes.empty:
            st.info("Não há cadastros pendentes.")
        else:
            st.dataframe(pendentes[["username", "full_name", "email", "matricula"]], use_container_width=True, hide_index=True)
            pendentes_list = pendentes["username"].tolist()
            to_approve = st.multiselect("Selecione usuários para aprovar:", options=pendentes_list)
            colap1, colap2 = st.columns(2)
            if colap1.button("✅ Aprovar selecionados", type="primary", use_container_width=True):
                if not to_approve:
                    st.warning("Selecione ao menos um usuário.")
                else:
                    base_url = get_app_base_url() or "https://SEU_DOMINIO"
                    for uname in to_approve:
                        idx = df_users.index[df_users["username"] == uname][0]
                        df_users.loc[idx, "status"] = "aprovado"
                        email = df_users.loc[idx, "email"].strip()
                        if email:
                            if not df_users.loc[idx, "password"]:
                                token = secrets.token_urlsafe(32)
                                expires = (datetime.now(tz_brasilia) + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
                                df_users.loc[idx, "reset_token"] = token
                                df_users.loc[idx, "reset_expires_at"] = expires
                                reset_link = f"{base_url}?reset_token={token}"
                                send_invite_to_set_password(email, reset_link)
                            else:
                                send_approved_email(email, base_url)
                    save_user_db(df_users)
                    st.success("Usuários aprovados e e-mails enviados (se configurado).")
                    safe_rerun()
            if colap2.button("🗑️ Rejeitar (remover) selecionados", use_container_width=True):
                if not to_approve:
                    st.warning("Selecione ao menos um usuário.")
                else:
                    to_remove = [u for u in to_approve if u != SUPERADMIN_USERNAME]
                    df_users = df_users[~df_users["username"].isin(to_remove)]
                    save_user_db(df_users)
                    st.success("Usuários removidos com sucesso.")
                    safe_rerun()

        st.markdown("---")

        st.subheader("Todos os usuários")
        st.dataframe(df_users[["username", "full_name", "email", "role", "status", "accepted_terms_on"]], use_container_width=True)

        selected_user = st.selectbox("Selecionar usuário para ações:", options=list(df_users["username"].values))
        if selected_user:
            idx = df_users.index[df_users["username"] == selected_user][0]
            st.write(f"Usuário: **{df_users.loc[idx,'username']}** — {df_users.loc[idx,'full_name']} — {df_users.loc[idx,'email']}")
            col1, col2, col3 = st.columns([1,1,1])
            with col1:
                if st.button("🔁 Forçar redefinição de senha (enviar link)"):
                    token = secrets.token_urlsafe(32)
                    expires = (datetime.now(tz_brasilia) + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
                    df_users.loc[idx,"reset_token"] = token
                    df_users.loc[idx,"reset_expires_at"] = expires
                    save_user_db(df_users)
                    base_url = get_app_base_url() or "https://SEU_DOMINIO"
                    reset_link = f"{base_url}?reset_token={token}"
                    if df_users.loc[idx,"email"].strip():
                        send_invite_to_set_password(df_users.loc[idx,"email"].strip(), reset_link)
                        st.success("Link de redefinição enviado (se SMTP configurado).")
                    else:
                        st.warning("Usuário não possui e-mail cadastrado.")
            with col2:
                if st.button("🛡️ Tornar admin / remover admin"):
                    current = df_users.loc[idx,"role"]
                    df_users.loc[idx,"role"] = "admin" if current != "admin" else "user"
                    save_user_db(df_users)
                    st.success(f"Função atualizada para: {df_users.loc[idx,'role']}")
                    safe_rerun()
            with col3:
                if st.button("🗑️ Excluir usuário"):
                    if df_users.loc[idx,"username"] == SUPERADMIN_USERNAME:
                        st.warning("Não é possível remover o superadmin.")
                    else:
                        try:
                            supabase.table('users').delete().eq('username', df_users.loc[idx,"username"]).execute()
                            st.cache_data.clear()
                            st.success("Usuário removido.")
                            safe_rerun()
                        except Exception as e:
                            st.error(f"Erro ao remover usuário do Supabase: {e}")

        st.markdown("---")

        st.subheader("Adicionar / Editar usuário")
        with st.form("admin_add_user_form", clear_on_submit=True):
            new_username = st.text_input("Usuário (login)")
            new_full_name = st.text_input("Nome completo")
            new_matricula = st.text_input("Matrícula")
            new_email = st.text_input("E-mail")
            new_role = st.selectbox("Tipo de Acesso", ["user", "admin"])
            pwd = st.text_input("Senha temporária (opcional)", type="password")
            approve_now = st.checkbox("Aprovar agora", value=True)
            if st.form_submit_button("Salvar usuário"):
                if not new_username.strip() or not new_full_name.strip() or not new_email.strip():
                    st.error("Usuário, nome e e-mail são obrigatórios.")
                else:
                    df_u = load_user_db()
                    if new_username in df_u["username"].values:
                        st.error("Nome de usuário já existe.")
                    else:
                        status = "aprovado" if approve_now else "pendente"
                        pwd_hash = ""
                        if pwd.strip():
                            ok, errs = validate_password_policy(pwd, username=new_username, email=new_email)
                            if not ok:
                                st.error("Regras de senha não atendidas:\n- " + "\n- ".join(errs))
                                st.stop()
                            pwd_hash = hash_password(pwd)
                        
                        new_row = {col: "" for col in REQUIRED_USER_COLUMNS}
                        new_row.update({
                            "username": new_username.strip(),
                            "password": pwd_hash,
                            "role": "admin" if new_role=="admin" else "user",
                            "full_name": new_full_name.strip(),
                            "matricula": new_matricula.strip(),
                            "email": new_email.strip(),
                            "status": status,
                            "last_password_change": datetime.now(tz_brasilia).strftime("%Y-%m-%d %H:%M:%S") if pwd_hash else "",
                            "force_password_reset": "" if pwd_hash else "1"
                        })
                        
                        try:
                            supabase.table('users').insert(new_row).execute()
                            st.cache_data.clear()
                            st.success("Usuário adicionado com sucesso!")
                        except Exception as e:
                            st.error(f"Erro ao adicionar usuário no Supabase: {e}")
                            st.stop()
                        
                        if status == "aprovado" and not pwd_hash and new_email.strip():
                            df_users_reloaded = load_user_db()
                            idx_list = df_users_reloaded.index[df_users_reloaded["username"] == new_username.strip()].tolist()
                            if idx_list:
                                idx2 = idx_list[0]
                                token = secrets.token_urlsafe(32)
                                expires = (datetime.now(tz_brasilia) + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
                                df_users_reloaded.loc[idx2,"reset_token"] = token
                                df_users_reloaded.loc[idx2,"reset_expires_at"] = expires
                                save_user_db(df_users_reloaded)
                                base_url = get_app_base_url() or "https://SEU_DOMINIO"
                                reset_link = f"{base_url}?reset_token={token}"
                                send_invite_to_set_password(new_email.strip(), reset_link)
                            else:
                                st.warning("Não foi possível enviar link de definição de senha para novo usuário.")
                        
                        safe_rerun()

    # SLA Mensal screen
    elif st.session_state.tela == "calc_simples":
        st.title("🖩 SLA Mensal")
        df_base = carregar_base()
        mensalidade = 0.0
        cliente = ""
        placa = ""
        with st.expander("🔍 Consultar Clientes e Placas"):
            if df_base is not None and not df_base.empty:
                df_display = df_base[['CLIENTE', 'PLACA', 'VALOR MENSALIDADE']].copy()
                df_display['VALOR MENSALIDADE'] = df_display['VALOR MENSALIDADE'].apply(formatar_moeda)
                st.dataframe(df_display, use_container_width=True, hide_index=True)
            else:
                st.info("Base De Clientes Faturamento.xlsx não encontrada. Você poderá digitar os dados manualmente abaixo.")
        col_left, col_right = st.columns([2,1])
        with col_left:
            st.subheader("1) Identificação")
            placa_in = st.text_input("Placa do veículo (digite e tecle Enter)", key="placa_simples").strip().upper()
            if placa_in and df_base is not None and not df_base.empty:
                hit = df_base[df_base["PLACA"].astype(str).str.upper() == placa_in]
                if not hit.empty:
                    placa = placa_in
                    cliente = str(hit.iloc[0]["CLIENTE"])
                    mensalidade = moeda_para_float(hit.iloc[0]["VALOR MENSALIDADE"])
                    st.success(f"Cliente: {cliente} | Mensalidade: {formatar_moeda(mensalidade)}")
                else:
                    st.warning("Placa não encontrada na base. Preencha os dados manualmente abaixo.")
            cliente = st.text_input("Cliente (caso não tenha sido localizado)", value=cliente)
            mensalidade = st.number_input("Mensalidade (R$)", min_value=0.0, step=0.01, format="%.2f", value=float(mensalidade) if mensalidade else 0.0)
            st.subheader("2) Período e Serviço")
            c1, c2 = st.columns(2)
            data_hoje = datetime.now(tz_brasilia).date()
            data_entrada = c1.date_input("Data de entrada", data_hoje)
            data_saida = c2.date_input("Data de saída", data_hoje + timedelta(days=3))
            feriados = c1.number_input("Feriados no período:", min_value=0, step=1, value=0)
            tipo_servico = c2.selectbox("Tipo de serviço (SLA)", [
                "Preventiva – 2 dias úteis",
                "Corretiva – 3 dias úteis",
                "Preventiva + Corretiva – 5 dias úteis",
                "Motor – 15 dias úteis"
            ])
            sla_map = {"Preventiva – 2 dias úteis": 2,"Corretiva – 3 dias úteis": 3,"Preventiva + Corretiva – 5 dias úteis": 5,"Motor – 15 dias úteis": 15}
            prazo_sla = sla_map.get(tipo_servico, 0)
            st.markdown("---")
            calc = st.button("Calcular SLA", type="primary")
            if calc:
                if not placa_in and not cliente:
                    st.error("Informe ao menos a placa ou o cliente.")
                elif data_entrada >= data_saida:
                    st.error("A data de saída deve ser posterior à data de entrada.")
                elif mensalidade <= 0:
                    st.error("Informe um valor de mensalidade válido.")
                else:
                    dias_uteis_manut, status, desconto, dias_exc = calcular_sla_simples(data_entrada, data_saida, prazo_sla, mensalidade, feriados)
                    st.session_state.resultado_sla = {
                        "cliente": cliente or "-",
                        "placa": placa_in or "-",
                        "tipo_servico": tipo_servico,
                        "dias_uteis_manut": int(dias_uteis_manut),
                        "prazo_sla": int(prazo_sla),
                        "dias_excedente": int(dias_exc),
                        "mensalidade": float(mensalidade),
                        "desconto": float(desconto),
                        "status": status
                    }
                    st.success("Cálculo realizado com sucesso!")
                    
                    pdf_buf = gerar_pdf_sla_simples(
                        cliente,
                        placa_in,
                        tipo_servico,
                        int(dias_uteis_manut),
                        int(prazo_sla),
                        int(dias_exc),
                        float(mensalidade),
                        float(desconto)
                    )
                    
                    registrar_analise(
                        username=st.session_state.get("username"),
                        tipo="sla_mensal",
                        dados=st.session_state.resultado_sla,
                        pdf_bytes=pdf_buf
                    )
        
        with col_right:
            st.subheader("Resultado")
            res = st.session_state.get("resultado_sla")
            if not res:
                st.info("Preencha os dados à esquerda e clique em 'Calcular SLA'.")
            else:
                st.write(f"- Status: {res['status']}")
                st.write(f"- Dias úteis da manutenção: {res['dias_uteis_manut']} dia(s)")
                st.write(f"- Prazo SLA: {res['prazo_sla']} dia(s)")
                st.write(f"- Dias excedidos: {res['dias_excedente']} dia(s)")
                st.write(f"- Mensalidade: {formatar_moeda(res['mensalidade'])}")
                st.write(f"- Desconto: {formatar_moeda(res['desconto'])}")

                try:
                    pdf_buf = gerar_pdf_sla_simples(res["cliente"], res["placa"], res["tipo_servico"], res["dias_uteis_manut"], res["prazo_sla"], res["dias_excedente"], res["mensalidade"], res["desconto"])
                    st.download_button("📥 Baixar PDF do Resultado", data=pdf_buf, file_name=f"sla_{res['placa'] or 'veiculo'}.pdf", mime="application/pdf")
                
                except NameError: 
                    st.error("A função 'gerar_pdf_sla_simples' não foi encontrada.")
                except Exception as e:
                    st.error(f"Erro ao tentar gerar PDF: {e}")

                if st.button("Limpar resultado"):
                    limpar_dados_simples()
                    safe_rerun()

    # Análise de Cenários screen
    elif st.session_state.tela == "calc_comparativa":
        st.title("📊 Análise de Cenários")
        if "cenarios" not in st.session_state:
            st.session_state.cenarios = []
        if "pecas_atuais" not in st.session_state:
            st.session_state.pecas_atuais = []
        if "mostrar_comparativo" not in st.session_state:
            st.session_state.mostrar_comparativo = False
        df_base = carregar_base()
        if df_base is None:
            st.error("❌ Arquivo 'Base De Clientes Faturamento.xlsx' não encontrado.")
            st.stop()
        if st.session_state.cenarios:
            st.markdown("---")
            st.header("📈 Cenários Calculados")
            df_cenarios = pd.DataFrame(st.session_state.cenarios)
            display_df = df_cenarios.copy()
            if "Detalhe Peças" in display_df.columns:
                display_df = display_df.drop(columns=["Detalhe Peças"])
            st.table(display_df)
            if len(st.session_state.cenarios) >= 2 and not st.session_state.mostrar_comparativo:
                if st.button("🏆 Comparar Cenários", type="primary"):
                    st.session_state.mostrar_comparativo = True
                    safe_rerun()
        if st.session_state.mostrar_comparativo:
            st.header("Análise Comparativa Final")
            df_cenarios = pd.DataFrame(st.session_state.cenarios)
            idx_min = df_cenarios["Total Final (R$)"].apply(moeda_para_float).idxmin()
            melhor = df_cenarios.loc[idx_min]
            st.success(f"🏆 Melhor cenário: {melhor['Serviço']} | Placa {melhor['Placa']} | Total Final: {melhor['Total Final (R$)']}")
            pdf_buffer = gerar_pdf_comparativo(df_cenarios, melhor)

            registrar_analise(
                username=st.session_state.get("username"),
                tipo="cenarios",
                dados={
                    "cenarios": st.session_state.cenarios,
                    "melhor": melhor.to_dict()
                },
                pdf_bytes=pdf_buffer
            )
            st.download_button("📥 Baixar Relatório PDF", pdf_buffer, "comparacao_cenarios_sla.pdf", "application/pdf")
            if st.button("🔄 Reiniciar Comparação", on_click=limpar_dados_comparativos, use_container_width=True, type="primary"):
                safe_rerun()
        else:
            st.markdown("---")
            st.header(f"📝 Preencher Dados para o Cenário {len(st.session_state.cenarios) + 1}")
            with st.expander("🔍 Consultar Clientes e Placas"):
                df_display = df_base[['CLIENTE', 'PLACA', 'VALOR MENSALIDADE']].copy()
                df_display['VALOR MENSALIDADE'] = df_display['VALOR MENSALIDADE'].apply(formatar_moeda)
                st.dataframe(df_display, use_container_width=True, hide_index=True)
            col_form, col_pecas = st.columns([2,1])
            with col_form:
                placa = st.text_input("1. Digite a placa e tecle Enter")
                cliente_info = None
                if placa:
                    placa_upper = placa.strip().upper()
                    cliente_row = df_base[df_base["PLACA"].astype(str).str.upper() == placa_upper]
                    if not cliente_row.empty:
                        cliente_info = {"cliente": cliente_row.iloc[0]["CLIENTE"], "mensalidade": moeda_para_float(cliente_row.iloc[0]["VALOR MENSALIDADE"])}
                        st.info(f"✅ Cliente: {cliente_info['cliente']} | Mensalidade: {formatar_moeda(cliente_info['mensalidade'])}")
                    else:
                        st.warning("❌ Placa não encontrada.")
                with st.form(key=f"form_cenario_{len(st.session_state.cenarios)}", clear_on_submit=True):
                    st.subheader("2. Detalhes do Serviço")
                    subcol1, subcol2 = st.columns(2)
                    data_hoje = datetime.now(tz_brasilia).date()
                    entrada = subcol1.date_input("📅 Data de entrada:", data_hoje)
                    saida = subcol2.date_input("📅 Data de saída:", data_hoje + timedelta(days=5))
                    feriados = subcol1.number_input("📌 Feriados no período:", min_value=0, step=1)
                    servico = subcol2.selectbox("🛠️ Tipo de serviço:", ["Preventiva – 2 dias úteis", "Corretiva – 3 dias úteis", "Preventiva + Corretiva – 5 dias úteis", "Motor – 15 dias úteis"])
                    with st.expander("Verificar Peças Adicionadas"):
                        if st.session_state.pecas_atuais:
                            for peca in st.session_state.pecas_atuais:
                                c1, c2 = st.columns([3,1])
                                c1.write(peca['nome'])
                                c2.write(formatar_moeda(peca['valor']))
                        else:
                            st.info("Nenhuma peça adicionada na coluna da direita.")
                    submitted = st.form_submit_button(f"➡️ Calcular Cenário {len(st.session_state.cenarios) + 1}", use_container_width=True, type="primary")
                    if submitted:
                        if not cliente_info:
                            st.error("Placa inválida ou não encontrada para submeter.")
                        elif entrada >= saida:
                            st.error("A data de saída deve ser posterior à de entrada.")
                        else:
                            cenario = calcular_cenario_comparativo(cliente_info["cliente"], placa.upper(), entrada, saida, feriados, servico, st.session_state.pecas_atuais, cliente_info["mensalidade"])
                            st.session_state.cenarios.append(cenario)
                            st.session_state.pecas_atuais = []
                            safe_rerun()
            with col_pecas:
                st.subheader("3. Gerenciar Peças")
                nome_peca = st.text_input("Nome da Peça", key="nome_peca_input")
                valor_peca = st.number_input("Valor (R$)", min_value=0.0, step=0.01, format="%.2f", key="valor_peca_input")
                if st.button("➕ Adicionar Peça", use_container_width=True):
                    if nome_peca and valor_peca > 0:
                        st.session_state.pecas_atuais.append({"nome": nome_peca, "valor": float(valor_peca)})
                        safe_rerun()
                    else:
                        st.warning("Preencha o nome e o valor da peça.")
                if st.session_state.pecas_atuais:
                    st.markdown("---")
                    st.write("Peças adicionadas:")
                    opcoes_pecas = [f"{p['nome']} - {formatar_moeda(p['valor'])}" for p in st.session_state.pecas_atuais]
                    pecas_para_remover = st.multiselect("Selecione para remover:", options=opcoes_pecas)
                    if st.button("🗑️ Remover Selecionadas", type="secondary", use_container_width=True):
                        if pecas_para_remover:
                            nomes_para_remover = [item.split(' - ')[0] for item in pecas_para_remover]
                            st.session_state.pecas_atuais = [p for p in st.session_state.pecas_atuais if p['nome'] not in nomes_para_remover]
                            safe_rerun()
                        else:
                            st.warning("Nenhuma peça foi selecionada.")

    # =========================
    # Tela: Abrir Ticket (usuário comum)
    # =========================
    elif st.session_state.tela == "tickets":
        st.title("💬 Abrir Ticket de Suporte")
        st.info("Use este canal para reportar erros, dúvidas ou sugerir melhorias.")

        with st.form("abrir_ticket"):
            assunto = st.text_input("Assunto")
            descricao = st.text_area("Descreva o problema ou sugestão")
            enviar = st.form_submit_button("Enviar Ticket", type="primary")
        if enviar:
            if not assunto.strip() or not descricao.strip():
                st.error("Preencha todos os campos.")
            else:
                novo_id = str(uuid.uuid4())
                now = datetime.now(tz_brasilia).strftime("%Y-%m-%d %H:%M")
                
                novo_ticket = {
                    "id": novo_id,
                    "username": st.session_state.get("username"),
                    "full_name": st.session_state.get("full_name"),
                    "email": st.session_state.get("email"),
                    "assunto": assunto.strip(),
                    "descricao": descricao.strip(),
                    "status": "aberto",
                    "resposta": "",
                    "data_criacao": now,
                    "data_resposta": ""
                }
                
                try:
                    supabase.table('tickets').insert(novo_ticket).execute()
                    st.cache_data.clear()
                    st.success("Ticket enviado com sucesso!")
                    safe_rerun()
                except Exception as e:
                    st.error(f"Erro ao salvar ticket no Supabase: {e}")

        df = load_tickets()
        meus = df[df["username"] == st.session_state.get("username")]
        if not meus.empty:
            st.markdown("### Meus Tickets")
            for _, row in meus.sort_values("data_criacao", ascending=False).iterrows():
                st.markdown(f"""
                <div style="border:1px solid #444;padding:10px;border-radius:8px;margin-bottom:8px;">
                <b>Assunto:</b> {row['assunto']}<br>
                <b>Status:</b> {row['status'].capitalize()}<br>
                <b>Data:</b> {row['data_criacao']}<br>
                <b>Descrição:</b> {row['descricao']}<br>
                <b>Resposta:</b> {row['resposta'] if row['resposta'] else '<i>Aguardando resposta</i>'}
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("Você ainda não abriu nenhum ticket.")

    # =========================
    # Tela: Relatório de Análises (ATUALIZADA)
    # =========================
    elif st.session_state.tela == "relatorio_analises":
        if not user_is_admin() and not user_is_superadmin():
            st.error("Acesso negado."); ir_para_home(); safe_rerun(); st.stop()
            
        st.title("📑 Relatório de Análises Realizadas")
        df = load_analises()
        
        if df.empty:
            st.info("Nenhuma análise encontrada.")
        else:
            # --- 💡 INÍCIO DA NOVA LÓGICA DE FILTRO 💡 ---
            opcoes_ano = ["Todos"]
            meses_map = {
                'Janeiro': 1, 'Fevereiro': 2, 'Março': 3, 'Abril': 4, 'Maio': 5, 'Junho': 6,
                'Julho': 7, 'Agosto': 8, 'Setembro': 9, 'Outubro': 10, 'Novembro': 11, 'Dezembro': 12
            }
            opcoes_mes = ["Todos"] + list(meses_map.keys())

            if not df.empty:
                df['data_hora_dt'] = pd.to_datetime(df['data_hora'], errors='coerce')
                df = df.dropna(subset=['data_hora_dt']) 
                
                if not df.empty:
                    df['ano_filtro'] = df['data_hora_dt'].dt.year
                    df['mes_filtro'] = df['data_hora_dt'].dt.month
                    
                    anos_disponiveis = sorted(df['ano_filtro'].unique(), reverse=True)
                    opcoes_ano = ["Todos"] + [int(a) for a in anos_disponiveis]
            # --- FIM DA NOVA LÓGICA ---

            usuarios = ["Todos"] + sorted(list(df["username"].unique()))
            
            # --- 💡 NOVOS FILTROS (EM COLUNAS) 💡 ---
            col1, col2, col3 = st.columns(3)
            with col1:
                usuario_sel = st.selectbox("Filtrar por usuário:", usuarios)
            with col2:
                ano_sel = st.selectbox("Filtrar por ano:", opcoes_ano)
            with col3:
                mes_sel = st.selectbox("Filtrar por mês:", opcoes_mes)
                
            tipo_sel = st.selectbox("Tipo de análise:", ["Todos", "cenarios", "sla_mensal"])
            # --- FIM DOS NOVOS FILTROS ---
                
            # Aplicar filtros
            if usuario_sel != "Todos":
                df = df[df["username"] == usuario_sel]
            if tipo_sel != "Todos":
                df = df[df["tipo"] == tipo_sel]
            if ano_sel != "Todos":
                df = df[df['ano_filtro'] == ano_sel]
            if mes_sel != "Todos":
                df = df[df['mes_filtro'] == meses_map[mes_sel]]
                
            st.write(f"Total de análises: {len(df)}")
            
            if not df.empty:
                
                # 1. Construir a URL pública do Supabase
                supabase_public_url = f"{url}/storage/v1/object/public"
                
                # 2. Criar o DataFrame "achatado"
                df_flat = pd.DataFrame([extrair_linha_relatorio(row, supabase_public_url) for _, row in df.iterrows()])

                # 3. Adiciona coluna Economia (usando o 'df' original filtrado)
                df_flat["Economia"] = [calcular_economia(row) for _, row in df.iterrows()]
                
                # 4. Reordena as colunas
                colunas = [
                    "Cliente", "Placa", "Serviço", "Valor Final", "Economia",
                    "Usuário", "Data/Hora", "PDF"
                ]
                colunas_finais = [c for c in colunas if c in df_flat.columns]
                df_flat = df_flat[colunas_finais]

                # 5. Botão de download do Excel
                excel_bytes = gerar_excel_moderno(df_flat)
                st.download_button(
                    "⬇️ Baixar relatório Excel (moderno)",
                    data=excel_bytes,
                    file_name="relatorio_analises.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    help="Clique para baixar o relatório já formatado para Excel!"
                )
                
                # 6. Botão de download do CSV "achatado" (com separador ;)
                st.download_button(
                    "⬇️ Baixar relatório CSV (Excel)",
                    data=df_flat.to_csv(index=False, sep=";", encoding="utf-8"),
                    file_name="relatorio_analises.csv",
                    mime="text/csv",
                    help="Clique para baixar o relatório em CSV simples (compatível com Excel)."
                )
                
                st.markdown("---") # Divisor

                # 7. --- 💡 INÍCIO DA CORREÇÃO DO HTML 💡 ---
                for idx, row in df_flat.iterrows():
                    economia_html = f"<b>Economia:</b> {row['Economia']}<br>" if row['Economia'] else ""
                    
                    # Monta a string HTML primeiro
                    html_string = f"""
                    <div style="border:1px solid #444;padding:10px;border-radius:8px;margin-bottom:8px;">
                        <b>Cliente:</b> {row['Cliente']}<br>
                        <b>Placa:</b> {row['Placa']}<br>
                        <b>Serviço:</b> {row['Serviço']}<br>
                        <b>Valor Final:</b> {row['Valor Final']}<br>
                        {economia_html}
                        <b>Usuário:</b> {row['Usuário']}<br>
                        <b>Data/Hora:</b> {row['Data/Hora']}<br>
                        <a href="{row['PDF']}" target="_blank" style="color: #60a5fa; text-decoration: none;">📥 Baixar PDF</a>
                    </div>
                    """
                    # Passa a string pronta para o markdown
                    st.markdown(html_string, unsafe_allow_html=True)
                # --- 💡 FIM DA CORREÇÃO DO HTML 💡 ---
                
            else:
                st.info("Nenhuma análise encontrada para o filtro selecionado.")
            
        if st.button("Voltar para Home"):
            ir_para_home(); safe_rerun()
        
    # =========================
    # Tela: Gerenciar Tickets (superadmin)
    # =========================
    elif st.session_state.tela == "admin_tickets":
        if not user_is_superadmin():
            st.error("Acesso negado."); ir_para_home(); safe_rerun(); st.stop()
        
        st.title("📋 Gerenciar Tickets de Suporte")
        df = load_tickets()

        abertos = df[df["status"] == "aberto"]
        if abertos.empty:
            st.info("Nenhum ticket aberto.")
        else:
            for idx, row in abertos.sort_values("data_criacao").iterrows():
                st.markdown(f"""
                <div style="border:1px solid #444;padding:10px;border-radius:8px;margin-bottom:8px;">
                <b>ID:</b> {row['id']}<br>
                <b>Usuário:</b> {row['full_name']} ({row['username']})<br>
                <b>Email:</b> {row['email']}<br>
                <b>Assunto:</b> {row['assunto']}<br>
                <b>Data:</b> {row['data_criacao']}<br>
                <b>Descrição:</b> {row['descricao']}<br>
                """, unsafe_allow_html=True)
                with st.form(f"responder_{row['id']}"):
                    resposta = st.text_area("Resposta", value=row['resposta'])
                    col1, col2 = st.columns(2)
                    responder = col1.form_submit_button("Responder e Fechar", type="primary")
                    ignorar = col2.form_submit_button("Ignorar (Fechar sem resposta)")
                if responder or ignorar:
                    df.loc[df["id"] == row["id"], "resposta"] = resposta if responder else "Ticket fechado sem resposta."
                    df.loc[df["id"] == row["id"], "status"] = "fechado"
                    df.loc[df["id"] == row["id"], "data_resposta"] = datetime.now(tz_brasilia).strftime("%Y-%m-%d %H:%M")
                    save_tickets(df)
                    st.success("Ticket fechado!")
                    safe_rerun()
                st.markdown("</div>", unsafe_allow_html=True)

        fechados = df[df["status"] == "fechado"]
        if not fechados.empty:
            with st.expander("Ver tickets fechados"):
                for _, row in fechados.sort_values("data_resposta", ascending=False).iterrows():
                    st.markdown(f"""
                    <div style="border:1px solid #888;padding:8px;border-radius:8px;margin-bottom:6px;">
                    <b>ID:</b> {row['id']}<br>
                    <b>Usuário:</b> {row['full_name']}<br>
                    <b>Assunto:</b> {row['assunto']}<br>
                    <b>Data:</b> {row['data_criacao']}<br>
                    <b>Descrição:</b> {row['descricao']}<br>
                    <b>Resposta:</b> {row['resposta']}<br>
                    <b>Respondido em:</b> {row['data_resposta']}
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.warning("Nenhum ticket fechado encontrado.")
        
    else:
        st.error("Tela não encontrada ou ainda não implementada.")
        if st.button("Voltar para Home"):
            ir_para_home(); safe_rerun()

    st.markdown("</div>", unsafe_allow_html=True)

# End of file
