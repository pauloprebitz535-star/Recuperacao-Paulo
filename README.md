# Almoxarifado - Operação "Cadê o Equipamento?"

API **somente back end** (sem tela) para controle de empréstimo de equipamentos de um almoxarifado.

**Tecnologias:** Python, FastAPI, JWT (PyJWT), bcrypt, SQLAlchemy e MySQL (acessado por túnel SSH).

---

## 1. O que o sistema faz

Existem três perfis de usuário, cada um com uma única responsabilidade:

| Perfil | Permissão |
|---|---|
| **Usuário comum** | Solicitar empréstimos |
| **Gestor** | Aprovar empréstimos e registrar devoluções |
| **Administrador** | Cadastrar equipamentos |

As permissões são estritas: o gestor **não** cadastra equipamentos e o usuário comum **não** acessa as rotas de aprovação e de cadastro. Qualquer tentativa fora do perfil retorna **403**.

Entidades modeladas: **usuários**, **equipamentos** e **empréstimos**.

---

## 2. Usuários para avaliação

Os usuários `admin` e `gestor` são criados automaticamente na primeira execução.

| Perfil | Usuário (`username`) | Senha (`password`) |
|---|---|---|
| Administrador | `admin` | `admin123` |
| Gestor | `gestor` | `gestor123` |
| Usuário comum | criado pela rota `POST /auth/registrar` | definida no cadastro |

Sugestão de usuário comum para teste: `{"username": "joao", "senha": "123456"}`.

---

## 3. Como executar

### Pré-requisitos
- Python 3.10 ou superior
- Acesso de rede ao servidor SSH e ao banco MySQL (rede da instituição ou VPN)

### Passo a passo (Windows / PowerShell)

```powershell
# 1. Dentro da pasta do projeto, crie e ative o ambiente virtual
python -m venv venv
.\venv\Scripts\Activate.ps1

# 2. Instale as dependências
pip install -r requirements.txt

# 3. Crie o arquivo .env (veja a seção 4)
copy .env.example .env

# 4. Rode a API
fastapi dev main.py
```

Se o PowerShell bloquear a ativação do venv, rode antes:
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`

Ao subir, o sistema **abre o túnel SSH automaticamente**, conecta no MySQL, cria as tabelas e os usuários iniciais. Aparecem no terminal as mensagens:

```
✔ Conectado ao banco '...'
Application startup complete.
```

A API fica em **http://127.0.0.1:8000** e a documentação interativa em **http://127.0.0.1:8000/docs**.

---

## 4. Configuração do banco (arquivo `.env`)

O arquivo `.env.example` traz todas as variáveis. Copie para `.env` e preencha com os dados de acesso ao SSH e ao MySQL (as credenciais do banco **não** estão neste repositório por segurança e são informadas separadamente).

| Variável | Descrição |
|---|---|
| `SSH_HOST`, `SSH_PORT`, `SSH_USER`, `SSH_PASSWORD` | Dados do servidor SSH (túnel). Deixe `SSH_HOST` vazio para conectar direto no MySQL |
| `DB_HOST`, `DB_PORT` | Endereço do MySQL visto de dentro do servidor SSH (normalmente `127.0.0.1` e `3306`) |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD` | Banco, usuário e senha do MySQL |
| `LOCAL_PORT` | Porta local do túnel (padrão `3307`) |

### Tabelas
As tabelas são criadas automaticamente na inicialização (não é preciso rodar nenhum script SQL):

- `usuarios2`
- `equipamentos2`
- `emprestimos2`

> O sufixo `2` evita conflito com tabelas de atividades anteriores no mesmo banco.

---

## 5. Como fazer login

A autenticação usa **JWT (Bearer Token)**. O token vale **60 minutos**.

### 5.1 Pela página `/docs` (mais simples)

1. Abra http://127.0.0.1:8000/docs
2. Clique em **Authorize** (cadeado, canto superior direito).
3. Preencha apenas `username` e `password` (ex.: `admin` / `admin123`). Deixe `client_id` e `client_secret` em branco.
4. Clique em **Authorize** e depois em **Close**.
5. Teste as rotas com **Try it out > Execute**. O token é enviado automaticamente.

Para trocar de usuário: **Authorize > Logout** e entre com outro. Para conferir quem está logado, use `GET /auth/me`.

### 5.2 Por um cliente de API (Postman, Insomnia, Thunder Client etc.)

**Passo 1 - Obter o token**

- Método **POST**, URL `http://127.0.0.1:8000/auth/login`
- Body no formato **`x-www-form-urlencoded`** (não é JSON), escrito em uma linha:

```
username=admin&password=admin123
```

- A resposta traz o token:

```json
{"access_token": "eyJhbGciOi...", "token_type": "bearer"}
```

**Passo 2 - Usar o token nas demais rotas**

Copie o valor de `access_token` (sem aspas) e envie no cabeçalho:

```
Authorization: Bearer eyJhbGciOi...
```

Nos clientes com aba **Authorization**, escolha o tipo **Bearer** e cole o token no campo.

### 5.3 Pelo PowerShell

```powershell
$r = curl.exe -s -X POST http://127.0.0.1:8000/auth/login -d "username=gestor&password=gestor123" | ConvertFrom-Json
$t = $r.access_token
curl.exe -i http://127.0.0.1:8000/auth/me -H "Authorization: Bearer $t"
```

---

## 6. Rotas

| Rota | Quem acessa |
|---|---|
| `POST /auth/registrar` | Qualquer pessoa (cria usuário **comum**) |
| `POST /auth/login` | Qualquer pessoa |
| `GET /auth/me` | Qualquer usuário logado |
| `GET /equipamentos` | Qualquer usuário logado |
| `POST /equipamentos` | **Administrador** |
| `POST /emprestimos` | **Usuário comum** |
| `GET /emprestimos` | Logado (comum vê só os seus; gestor e admin veem todos) |
| `PATCH /emprestimos/{id}/aprovar` | **Gestor** |
| `PATCH /emprestimos/{id}/devolver` | **Gestor** |

Corpos de exemplo (JSON):

```json
// POST /auth/registrar
{"username": "joao", "senha": "123456"}

// POST /equipamentos
{"nome": "Furadeira", "codigo": "FUR-001"}

// POST /emprestimos
{"equipamento_id": 1}
```

### Fluxo de um empréstimo

1. O usuário comum solicita: status `solicitado`.
2. O gestor aprova: o equipamento fica indisponível e o status vira `aprovado`.
3. O gestor registra a devolução: o equipamento volta a ficar disponível e o status vira `devolvido`.

Cada etapa registra quem a executou (`aprovado_por` e `devolvido_por`).

---

## 7. Roteiro de avaliação

Faça os testes pela página `/docs` (ou cliente de API) na ordem abaixo.

| # | Logado como | Rota | Esperado |
|---|---|---|---|
| 1 | `admin` | `POST /equipamentos` `{"nome":"Furadeira","codigo":"FUR-001"}` | **201** |
| 2 | `admin` | `POST /equipamentos` com o mesmo código | **409** |
| 3 | `gestor` | `POST /equipamentos` com outro código | **403** |
| 4 | ninguém | `GET /equipamentos` | **401** |
| 5 | ninguém | `POST /auth/registrar` `{"username":"joao","senha":"123456"}` | **201** |
| 6 | `joao` | `POST /emprestimos` `{"equipamento_id":1}` | **201** (`solicitado`) |
| 7 | `joao` | `PATCH /emprestimos/{id}/aprovar` | **403** |
| 8 | `gestor` | `PATCH /emprestimos/{id}/aprovar` | **200** (`aprovado`) |
| 9 | `joao` | `POST /emprestimos` com o mesmo equipamento | **409** (indisponível) |
| 10 | `gestor` | `PATCH /emprestimos/{id}/devolver` | **200** (`devolvido`) |
| 11 | `gestor` | `PATCH /emprestimos/999/aprovar` | **404** |
| 12 | `joao` | `GET /emprestimos` | Lista só os dele |

Use o `id` real do empréstimo retornado no passo 6.

### Teste completo por script (PowerShell)

Com a API rodando, este bloco executa o fluxo inteiro (cadastro, solicitação, aprovação e devolução):

```powershell
$base = "http://127.0.0.1:8000"

function Login($u, $p) {
  (Invoke-RestMethod -Method Post -Uri "$base/auth/login" -Body @{username=$u; password=$p}).access_token
}

$admin  = Login "admin" "admin123"
$gestor = Login "gestor" "gestor123"

# 1. Admin cadastra um equipamento
$eq = Invoke-RestMethod -Method Post -Uri "$base/equipamentos" `
  -Headers @{Authorization="Bearer $admin"} -ContentType "application/json" `
  -Body '{"nome":"Furadeira","codigo":"FUR-001"}'
$eq

# 2. Cria o usuário comum e faz login
Invoke-RestMethod -Method Post -Uri "$base/auth/registrar" `
  -ContentType "application/json" -Body '{"username":"joao","senha":"123456"}'
$joao = Login "joao" "123456"

# 3. Comum solicita o empréstimo
$emp = Invoke-RestMethod -Method Post -Uri "$base/emprestimos" `
  -Headers @{Authorization="Bearer $joao"} -ContentType "application/json" `
  -Body (@{equipamento_id=$eq.id} | ConvertTo-Json)
$emp

# 4. Gestor aprova
Invoke-RestMethod -Method Patch -Uri "$base/emprestimos/$($emp.id)/aprovar" `
  -Headers @{Authorization="Bearer $gestor"}

# 5. Gestor registra a devolução
Invoke-RestMethod -Method Patch -Uri "$base/emprestimos/$($emp.id)/devolver" `
  -Headers @{Authorization="Bearer $gestor"}
```

Se o equipamento `FUR-001` ou o usuário `joao` já existirem, a API responde 409. Nesse caso, mude o código do equipamento e use apenas `Login` para o usuário.

### Teste das permissões negadas (mostra o código HTTP)

```powershell
# Gestor tentando cadastrar equipamento -> 403
curl.exe -i -X POST http://127.0.0.1:8000/equipamentos -H "Authorization: Bearer $gestor" -H "Content-Type: application/json" -d '{\"nome\":\"Serra\",\"codigo\":\"SER-001\"}'

# Comum tentando aprovar -> 403
curl.exe -i -X PATCH http://127.0.0.1:8000/emprestimos/1/aprovar -H "Authorization: Bearer $joao"

# Sem token -> 401
curl.exe -i http://127.0.0.1:8000/equipamentos
```

---

## 8. Tratamento de exceções

As falhas de regra de negócio e de permissão são lançadas como **exceções de domínio** e traduzidas para códigos HTTP semânticos por um único tratador (`exception_handler`).

| Exceção | HTTP | Quando acontece |
|---|---|---|
| `CredenciaisInvalidas` | 401 | Usuário ou senha incorretos |
| `TokenInvalido` | 401 | Token ausente, malformado ou de usuário inexistente |
| `TokenExpirado` | 401 | Token com mais de 60 minutos |
| `PermissaoNegada` | 403 | O perfil não tem acesso à rota |
| `NaoEncontrado` | 404 | Equipamento ou empréstimo inexistente |
| `Conflito` | 409 | Código duplicado, equipamento indisponível, status inválido |
| (validação do FastAPI) | 422 | Dados enviados no formato errado |

Formato da resposta de erro:

```json
{"erro": "PermissaoNegada", "detalhe": "Seu perfil não tem permissão para esta operação."}
```

As respostas 401 incluem o cabeçalho `WWW-Authenticate: Bearer`.

---

## 9. Decisões de projeto

- **Controle por perfil:** a dependência `exigir_perfil(...)` protege cada rota e lança `PermissaoNegada` quando o perfil não é o permitido.
- **Segurança:** senhas armazenadas com hash **bcrypt**; tokens **JWT** assinados (HS256) com expiração de 60 minutos.
- **Autocadastro seguro:** `POST /auth/registrar` sempre cria usuário **comum**. Gestor e admin só existem pelos usuários iniciais.
- **Consistência:** o equipamento só fica indisponível na aprovação e volta a ficar disponível na devolução.
- **Conexão com o banco:** o túnel SSH e a conexão com o MySQL são abertos na inicialização da aplicação (`lifespan`), e as tabelas são criadas automaticamente.

---

## 10. Problemas comuns

| Sintoma | Causa e solução |
|---|---|
| `fastapi` não é reconhecido | Ative o venv (`.\venv\Scripts\Activate.ps1`) e rode `pip install -r requirements.txt` |
| Erro de política de execução ao ativar o venv | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` |
| `No module named 'pymysql'` | Dependências não instaladas: `pip install -r requirements.txt` |
| `Não foi possível conectar ao banco` | Confira o `.env`, a rede/VPN e as credenciais do SSH e do MySQL |
| `Address already in use` (porta 3307) | Há um túnel SSH manual aberto; feche-o |
| `DSSKey` ao abrir o túnel | `pip install "paramiko<4"` |
| `Unknown column ...` | Já existe tabela com o mesmo nome e outra estrutura; use outros nomes de tabela |
| Login retorna **422** | O corpo precisa ser `x-www-form-urlencoded` em uma linha (`username=...&password=...`), não JSON |
| Rotas retornam **401** | Falta o cabeçalho `Authorization: Bearer <token>` ou o token expirou (faça login de novo) |
| Rota retorna **403** | O usuário logado não tem o perfil exigido pela rota |

---

## 11. Estrutura do projeto

```
.
├── main.py             # API completa (modelos, segurança, rotas, tratamento de erros)
├── requirements.txt    # Dependências
├── .env.example        # Modelo das variáveis de ambiente
├── .env                # Credenciais reais (NÃO versionar nem enviar)
└── README.md
```
