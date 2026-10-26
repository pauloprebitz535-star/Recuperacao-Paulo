import os
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.engine import URL
from sshtunnel import SSHTunnelForwarder
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from enum import Enum
from sqlalchemy.engine import URL
import bcrypt
import jwt
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ForeignKey, String, create_engine, select
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)

# ----------------------------------------------------------------------
# Configuração
# ----------------------------------------------------------------------
load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "troque-esta-chave-em-producao")
ALGORITHM = "HS256"
TOKEN_EXPIRA_MINUTOS = 60

SSH_HOST = os.getenv("SSH_HOST")
SSH_PORT = int(os.getenv("SSH_PORT", "22"))
SSH_USER = os.getenv("SSH_USER")
SSH_PASSWORD = os.getenv("SSH_PASSWORD")

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")  # visto de dentro do servidor SSH
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
LOCAL_PORT = int(os.getenv("LOCAL_PORT", "3307"))

# Se há SSH_HOST, o app conecta pela porta local do túnel; senão, direto.
DATABASE_URL = URL.create(
    "mysql+pymysql",
    username=DB_USER,
    password=DB_PASSWORD,
    host="127.0.0.1" if SSH_HOST else DB_HOST,
    port=LOCAL_PORT if SSH_HOST else DB_PORT,
    database=DB_NAME,
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


def abrir_tunel() -> SSHTunnelForwarder | None:
    if not SSH_HOST:
        return None
    tunel = SSHTunnelForwarder(
        (SSH_HOST, SSH_PORT),
        ssh_username=SSH_USER,
        ssh_password=SSH_PASSWORD,
        remote_bind_address=(DB_HOST, DB_PORT),
        local_bind_address=("127.0.0.1", LOCAL_PORT),
        allow_agent=False,
        host_pkey_directories=[],
    )
    tunel.start()
    return tunel


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
      db.close()
# ----------------------------------------------------------------------
# Entidades (banco de dados)
# ----------------------------------------------------------------------
class Perfil(str, Enum):
    COMUM = "comum"
    GESTOR = "gestor"
    ADMIN = "admin"


class StatusEmprestimo(str, Enum):
    SOLICITADO = "solicitado"
    APROVADO = "aprovado"
    DEVOLVIDO = "devolvido"


class Base(DeclarativeBase):
    pass


class Usuario(Base):
    __tablename__ = "usuarios2"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    senha_hash: Mapped[str] = mapped_column(String(100))
    perfil: Mapped[str] = mapped_column(String(10), default=Perfil.COMUM.value)


class Equipamento(Base):
    __tablename__ = "equipamentos2"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(100))
    codigo: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    disponivel: Mapped[bool] = mapped_column(default=True)


class Emprestimo(Base):
    __tablename__ = "emprestimos2"
    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios2.id"))
    equipamento_id: Mapped[int] = mapped_column(ForeignKey("equipamentos2.id"))
    status: Mapped[str] = mapped_column(
        String(15), default=StatusEmprestimo.SOLICITADO.value
    )
    solicitado_em: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )
    aprovado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios2.id"))
    devolvido_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios2.id"))


# ----------------------------------------------------------------------
# Exceções de domínio -> traduzidas para códigos HTTP semânticos
# ----------------------------------------------------------------------
class ErroAplicacao(Exception):
    status_code = 500
    detalhe = "Erro interno."

    def __init__(self, detalhe: str | None = None):
        if detalhe:
            self.detalhe = detalhe
        super().__init__(self.detalhe)


class CredenciaisInvalidas(ErroAplicacao):
    status_code = 401
    detalhe = "Usuário ou senha inválidos."


class TokenInvalido(ErroAplicacao):
    status_code = 401
    detalhe = "Token inválido ou ausente."


class TokenExpirado(ErroAplicacao):
    status_code = 401
    detalhe = "Token expirado. Faça login novamente."


class PermissaoNegada(ErroAplicacao):
    status_code = 403
    detalhe = "Seu perfil não tem permissão para esta operação."


class NaoEncontrado(ErroAplicacao):
    status_code = 404
    detalhe = "Recurso não encontrado."


class Conflito(ErroAplicacao):
    status_code = 409
    detalhe = "Conflito com o estado atual do recurso."


# ----------------------------------------------------------------------
# Segurança: senha + JWT
# ----------------------------------------------------------------------
def gerar_hash(senha: str) -> str:
    return bcrypt.hashpw(senha.encode(), bcrypt.gensalt()).decode()


def verificar_senha(senha: str, senha_hash: str) -> bool:
    return bcrypt.checkpw(senha.encode(), senha_hash.encode())


def criar_token(usuario: Usuario) -> str:
    agora = datetime.now(timezone.utc)
    payload = {
        "sub": str(usuario.id),
        "perfil": usuario.perfil,
        "iat": agora,
        "exp": agora + timedelta(minutes=TOKEN_EXPIRA_MINUTOS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def usuario_atual(
    token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> Usuario:
    if not token:
        raise TokenInvalido()
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise TokenExpirado()
    except jwt.PyJWTError:
        raise TokenInvalido()

    usuario = db.get(Usuario, int(payload["sub"]))
    if not usuario:
        raise TokenInvalido()
    return usuario


def exigir_perfil(*perfis: Perfil):
    """Dependência que só deixa passar quem tem um dos perfis informados."""
    permitidos = {p.value for p in perfis}

    def verificador(usuario: Usuario = Depends(usuario_atual)) -> Usuario:
        if usuario.perfil not in permitidos:
            raise PermissaoNegada()
        return usuario

    return verificador


# ----------------------------------------------------------------------
# Schemas (entrada e saída)
# ----------------------------------------------------------------------
class RegistroIn(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    senha: str = Field(min_length=6, max_length=72)


class UsuarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    perfil: Perfil


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class EquipamentoIn(BaseModel):
    nome: str = Field(min_length=2, max_length=100)
    codigo: str = Field(min_length=1, max_length=50)


class EquipamentoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nome: str
    codigo: str
    disponivel: bool


class EmprestimoIn(BaseModel):
    equipamento_id: int


class EmprestimoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    usuario_id: int
    equipamento_id: int
    status: StatusEmprestimo
    solicitado_em: datetime
    aprovado_por: int | None
    devolvido_por: int | None


# ----------------------------------------------------------------------
# Aplicação
# ----------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Abre o túnel, conecta no banco, cria tabelas e usuários iniciais."""
    tunel = abrir_tunel()
    try:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as e:
            raise RuntimeError(f"Não foi possível conectar ao banco: {e}") from e
        print(f"✔ Conectado ao banco '{DB_NAME}'")

        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            iniciais = [
                ("admin", "admin123", Perfil.ADMIN),
                ("gestor", "gestor123", Perfil.GESTOR),
            ]
            for username, senha, perfil in iniciais:
                existe = db.scalar(select(Usuario).where(Usuario.username == username))
                if not existe:
                    db.add(
                        Usuario(
                            username=username,
                            senha_hash=gerar_hash(senha),
                            perfil=perfil.value,
                        )
                    )
            db.commit()
        yield
    finally:
        engine.dispose()
        if tunel:
            tunel.stop()


app = FastAPI(title="Almoxarifado - Cadê o Equipamento?", lifespan=lifespan)


@app.exception_handler(ErroAplicacao)
async def tratar_erro_aplicacao(request: Request, exc: ErroAplicacao):
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    return JSONResponse(
        status_code=exc.status_code,
        content={"erro": type(exc).__name__, "detalhe": exc.detalhe},
        headers=headers,
    )

# ----------------------------------------------------------------------
# Autenticação
# ----------------------------------------------------------------------
@app.post("/auth/registrar", response_model=UsuarioOut, status_code=201, tags=["Auth"])
def registrar(dados: RegistroIn, db: Session = Depends(get_db)):
    """Autocadastro: sempre cria um usuário com perfil 'comum'."""
    if db.scalar(select(Usuario).where(Usuario.username == dados.username)):
        raise Conflito("Nome de usuário já está em uso.")
    usuario = Usuario(
        username=dados.username,
        senha_hash=gerar_hash(dados.senha),
        perfil=Perfil.COMUM.value,
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


@app.post("/auth/login", response_model=TokenOut, tags=["Auth"])
def login(
    form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
):
    usuario = db.scalar(select(Usuario).where(Usuario.username == form.username))
    if not usuario or not verificar_senha(form.password, usuario.senha_hash):
        raise CredenciaisInvalidas()
    return TokenOut(access_token=criar_token(usuario))


@app.get("/auth/me", response_model=UsuarioOut, tags=["Auth"])
def me(usuario: Usuario = Depends(usuario_atual)):
    return usuario


# ----------------------------------------------------------------------
# Equipamentos
# ----------------------------------------------------------------------
@app.post(
    "/equipamentos", response_model=EquipamentoOut, status_code=201, tags=["Equipamentos"]
)
def cadastrar_equipamento(
    dados: EquipamentoIn,
    db: Session = Depends(get_db),
    _: Usuario = Depends(exigir_perfil(Perfil.ADMIN)),  # somente administrador
):
    if db.scalar(select(Equipamento).where(Equipamento.codigo == dados.codigo)):
        raise Conflito("Já existe um equipamento com esse código.")
    equipamento = Equipamento(nome=dados.nome, codigo=dados.codigo)
    db.add(equipamento)
    db.commit()
    db.refresh(equipamento)
    return equipamento


@app.get("/equipamentos", response_model=list[EquipamentoOut], tags=["Equipamentos"])
def listar_equipamentos(
    db: Session = Depends(get_db), _: Usuario = Depends(usuario_atual)
):
    return db.scalars(select(Equipamento)).all()


# ----------------------------------------------------------------------
# Empréstimos
# ----------------------------------------------------------------------
def buscar_emprestimo(db: Session, emprestimo_id: int) -> Emprestimo:
    emprestimo = db.get(Emprestimo, emprestimo_id)
    if not emprestimo:
        raise NaoEncontrado("Empréstimo não encontrado.")
    return emprestimo


@app.post(
    "/emprestimos", response_model=EmprestimoOut, status_code=201, tags=["Empréstimos"]
)
def solicitar_emprestimo(
    dados: EmprestimoIn,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_perfil(Perfil.COMUM)),  # somente usuário comum
):
    equipamento = db.get(Equipamento, dados.equipamento_id)
    if not equipamento:
        raise NaoEncontrado("Equipamento não encontrado.")
    if not equipamento.disponivel:
        raise Conflito("Equipamento indisponível no momento.")

    emprestimo = Emprestimo(usuario_id=usuario.id, equipamento_id=equipamento.id)
    db.add(emprestimo)
    db.commit()
    db.refresh(emprestimo)
    return emprestimo


@app.get("/emprestimos", response_model=list[EmprestimoOut], tags=["Empréstimos"])
def listar_emprestimos(
    db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_atual)
):
    """Comum vê só os seus; gestor e admin veem todos."""
    consulta = select(Emprestimo)
    if usuario.perfil == Perfil.COMUM.value:
        consulta = consulta.where(Emprestimo.usuario_id == usuario.id)
    return db.scalars(consulta).all()


@app.patch(
    "/emprestimos/{emprestimo_id}/aprovar",
    response_model=EmprestimoOut,
    tags=["Empréstimos"],
)
def aprovar_emprestimo(
    emprestimo_id: int,
    db: Session = Depends(get_db),
    gestor: Usuario = Depends(exigir_perfil(Perfil.GESTOR)),  # somente gestor
):
    emprestimo = buscar_emprestimo(db, emprestimo_id)
    if emprestimo.status != StatusEmprestimo.SOLICITADO.value:
        raise Conflito(f"Empréstimo já está '{emprestimo.status}'.")

    equipamento = db.get(Equipamento, emprestimo.equipamento_id)
    if not equipamento.disponivel:
        raise Conflito("Equipamento indisponível no momento.")

    equipamento.disponivel = False
    emprestimo.status = StatusEmprestimo.APROVADO.value
    emprestimo.aprovado_por = gestor.id
    db.commit()
    db.refresh(emprestimo)
    return emprestimo


@app.patch(
    "/emprestimos/{emprestimo_id}/devolver",
    response_model=EmprestimoOut,
    tags=["Empréstimos"],
)
def registrar_devolucao(
    emprestimo_id: int,
    db: Session = Depends(get_db),
    gestor: Usuario = Depends(exigir_perfil(Perfil.GESTOR)),  # somente gestor
):
    emprestimo = buscar_emprestimo(db, emprestimo_id)
    if emprestimo.status != StatusEmprestimo.APROVADO.value:
        raise Conflito("Só é possível devolver um empréstimo aprovado.")

    equipamento = db.get(Equipamento, emprestimo.equipamento_id)
    equipamento.disponivel = True
    emprestimo.status = StatusEmprestimo.DEVOLVIDO.value
    emprestimo.devolvido_por = gestor.id
    db.commit()
    db.refresh(emprestimo)
    return emprestimo

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
