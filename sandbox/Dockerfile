FROM python:3.12-slim
WORKDIR /usr/local/app

COPY ./sandbox/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ./mcp_servers/sandbox_server/ .

CMD [ "python3", "server.py" ]