# Bot de Comunidade Gamer

## Antes de hospedar

1. Renomeie `.env.example` para `.env` e preencha `DISCORD_TOKEN`, ou crie a variável no Railway.
2. No Discord Developer Portal, ative **Server Members Intent** e **Message Content Intent**.
3. Convide o bot com permissões de Gerenciar Canais, Gerenciar Cargos, Gerenciar Mensagens, Mover Membros e Enviar Mensagens.

## Comandos principais

- `/setupservidor` cria a estrutura completa.
- `/config` configura cargos, logs, anti-link e canais.
- `/configticket` e `/ticket` configuram/publicam tickets.
- `/configeventos` cria e publica eventos.
- `/configconteudos` cria conteúdos, códigos e painéis.
- `/loja`, `/missoes`, `/daily`, `/perfil` e `/ranking` são para membros.
- `/configcalls` e `/painelcalls` configuram calls temporárias.
- `/ia` usa Gemini apenas se `GEMINI_API_KEY` estiver configurada.
