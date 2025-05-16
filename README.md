# Protocolo de Transferência de Arquivos UDP Confiável

Este projeto implementa um sistema cliente-servidor para transferência confiável de arquivos sobre UDP. Diferente do TCP, o UDP não garante entrega de pacotes, então este projeto implementa mecanismos adicionais como confirmações (ACKs), timeouts, retransmissões e checksums para garantir a entrega correta dos dados.

## Características

- Transferência de arquivos sobre UDP com garantia de entrega
- Detecção de erros usando checksums CRC32
- Reordenação de pacotes recebidos fora de ordem
- Retransmissão automática em caso de pacotes perdidos
- Simulação controlada de perda de pacotes para testes
- Identificação única de arquivos baixados no cliente
- Suporte para arquivos de qualquer tamanho
- Sistema de logs com timestamps para facilitar diagnósticos

## Estrutura do Projeto

```
.
├── client.py            # Cliente UDP que solicita e recebe arquivos
├── server.py            # Servidor UDP multithreaded para atender solicitações
├── gerar_arquivo_teste.py # Script para criar arquivos de teste com tamanho específico
├── info.dat             # Arquivo com informações do projeto
├── .gitignore           # Configuração para excluir diretórios de dados do controle de versão
├── files/               # Diretório com arquivos disponíveis para download
├── received/            # Diretório onde o cliente salva os arquivos baixados
└── README.md            # Este arquivo
```

## Como Executar

### Servidor

O servidor recebe um único argumento obrigatório: a porta UDP onde vai escutar conexões. Por padrão, os arquivos são servidos do diretório `files/` que é criado automaticamente se não existir.

```powershell
python server.py 5000
```

Este comando inicia o servidor na porta UDP 5000, servindo arquivos que estão na pasta `files/`.

### Cliente

O cliente utiliza o formato de URL `IP:Porta/arquivo` para especificar o servidor e o arquivo desejado:

```powershell
python client.py GET 127.0.0.1:5000/teste_1mb.dat
```

O comando acima solicita o arquivo `teste_1mb.dat` do servidor que está rodando em `127.0.0.1` (localhost) na porta `5000`. O arquivo será salvo na pasta `received/` com um prefixo único para evitar sobrescrever downloads anteriores.

### Simulando Perda de Pacotes

Para testar a robustez do protocolo, você pode simular perda de pacotes usando a opção `--loss`:

```powershell
python client.py GET 127.0.0.1:5000/teste_1mb.dat --loss 5
```

O comando acima configura o cliente para descartar aleatoriamente 5% dos pacotes recebidos, simulando uma conexão instável. O protocolo deve ser capaz de recuperar-se dessas perdas através de retransmissões.

## Protocolo de Comunicação

O protocolo implementa um mecanismo de transferência confiável sobre UDP:

1. O cliente envia uma solicitação `GET /arquivo` para o servidor
2. O servidor divide o arquivo em segmentos e os envia sequencialmente
3. Cada segmento possui um número de sequência único e um checksum CRC32
4. O cliente confirma o recebimento de cada segmento com um ACK
5. Segmentos não confirmados são retransmitidos após um timeout
6. O último segmento é marcado com uma flag especial (FLAG_LAST)
7. O cliente pode solicitar retransmissão específica de segmentos perdidos com comando RESEND
8. O servidor mantém uma janela de tempo para recuperação após o envio do último segmento

### Estrutura do Cabeçalho (18 bytes)

| Campo       | Tamanho | Descrição                               |
|-------------|---------|------------------------------------------|
| magic       | 2 bytes | Número mágico (0x0000) para validação    |
| type        | 1 byte  | Tipo do pacote (REQ=0, DATA=1, ACK=2, ERR=3) |
| seq_num     | 4 bytes | Número de sequência do segmento          |
| payload_len | 2 bytes | Comprimento do payload em bytes          |
| total_segs  | 4 bytes | Número total de segmentos do arquivo     |
| flags       | 1 byte  | Flags de controle (NORMAL=0, LAST=1)     |
| checksum    | 4 bytes | CRC32 para detecção de erros             |

## Mecanismos de Confiabilidade

O protocolo implementa vários mecanismos para garantir a entrega confiável sobre UDP:

- **Checksums CRC32**: Verificação de integridade em todos os pacotes para detectar corrupção
- **Timeouts adaptativos**: Retransmissão automática de pacotes não confirmados após um período
- **Confirmações (ACKs)**: O cliente envia confirmação para cada segmento recebido com sucesso
- **Números de sequência**: Garantem a ordenação correta e identificação de pacotes duplicados
- **Buffer de segmentos**: O cliente armazena segmentos fora de ordem para montagem posterior
- **Janela de recuperação**: O servidor mantém conexões ativas por um tempo após o envio do último segmento
- **Multithreading**: O servidor usa threads para atender múltiplos clientes simultaneamente
- **Registro de eventos**: Sistema de logs detalhados para diagnóstico de problemas

## Gerando Arquivos de Teste

O projeto inclui um utilitário para gerar arquivos de teste de tamanho específico:

```powershell
python gerar_arquivo_teste.py teste_20mb.dat 20
```

Este comando gera um arquivo de 20 MB com conteúdo aleatório chamado `teste_20mb.dat`.

## Arquivos baixados

Os arquivos baixados pelo cliente são salvos na pasta `received/` com um prefixo de 8 caracteres hexadecimais único para evitar sobrescrever downloads anteriores:

```
received/
├── 0e8ee01d_python.png
├── 251a24df_python.png
├── 5fb9b9dd_teste_15mb.dat
└── ...
```

## Autor

Mateus - Maio 2025
