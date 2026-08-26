import asyncio
import json
import os
import random
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv()

DB_PATH = Path("community_bot.sqlite3")
COLOR = discord.Color(0x2B2D31)
E = {
    "ticket": "<:ticket:1542264788942323954>", "support": "<:suporte:1542264787600146553>",
    "ok": "<:sucesso_animado:1542264786224681030>", "staff": "<:staff:1542264784047702056>",
    "room": "<:salas:1542264782596350132>", "exit": "<:sair:1542264784849822362>",
    "remove": "<:remover:1542264780201529484>", "clock": "<:relogio:1542264778662215811>",
    "trophy": "<:ranking_trofeu:1542264771229060227>", "gift": "<:presente:1542264773570330684>",
    "config": "<:config:1542264734575555274>", "pc": "<:computador:1542264733510533210>",
    "lock": "<:cadeado_privado:1542264731237359667>", "block": "<:bloqueado:1542264730159292476>",
    "refresh": "<:atualizar:1542264728238432296>", "bell": "<:anuncio_animado:1542264725583167518>",
    "alert": "<:alerta_staff_animado:1542264724195119196>", "add": "<:adicionar:1542264721003122729>",
}

def embed(title: str, text: str = "") -> discord.Embed:
    return discord.Embed(title=f"╭ {title} ╮", description=text, color=COLOR, timestamp=datetime.now(timezone.utc))

class Store:
    def __init__(self) -> None:
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS settings(guild_id INTEGER PRIMARY KEY, owner_role INTEGER, staff_role INTEGER, member_role INTEGER, logs_channel INTEGER, ticket_category INTEGER, anti_link INTEGER DEFAULT 1, call_category INTEGER, call_limit INTEGER DEFAULT 1, call_minutes INTEGER DEFAULT 60);
        CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id INTEGER,channel_id INTEGER,user_id INTEGER,status TEXT DEFAULT 'open');
        CREATE TABLE IF NOT EXISTS contents(id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id INTEGER,name TEXT,description TEXT,video_url TEXT,file_url TEXT,banner_url TEXT,active INTEGER DEFAULT 1,channel_id INTEGER,message_id INTEGER);
        CREATE TABLE IF NOT EXISTS codes(code TEXT PRIMARY KEY,content_id INTEGER,used_by INTEGER,used_at TEXT,expires_at TEXT);
        CREATE TABLE IF NOT EXISTS wallets(guild_id INTEGER,user_id INTEGER,xp INTEGER DEFAULT 0,coins INTEGER DEFAULT 0,last_daily TEXT,PRIMARY KEY(guild_id,user_id));
        CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id INTEGER,name TEXT,cost INTEGER,file_url TEXT,active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id INTEGER,name TEXT,description TEXT,prize TEXT,starts_at TEXT,banner_url TEXT,capacity INTEGER DEFAULT 48,status TEXT DEFAULT 'draft',channel_id INTEGER,message_id INTEGER);
        CREATE TABLE IF NOT EXISTS event_entries(event_id INTEGER,user_id INTEGER,PRIMARY KEY(event_id,user_id));
        CREATE TABLE IF NOT EXISTS temp_calls(channel_id INTEGER PRIMARY KEY,guild_id INTEGER,owner_id INTEGER,created_at TEXT);
        """)
        self.conn.commit()
    def settings(self, guild_id: int) -> sqlite3.Row:
        self.conn.execute("INSERT OR IGNORE INTO settings(guild_id) VALUES(?)", (guild_id,)); self.conn.commit()
        return self.conn.execute("SELECT * FROM settings WHERE guild_id=?", (guild_id,)).fetchone()
    def wallet(self,guild_id:int,user_id:int)->sqlite3.Row:
        self.conn.execute("INSERT OR IGNORE INTO wallets(guild_id,user_id) VALUES(?,?)",(guild_id,user_id));self.conn.commit()
        return self.conn.execute("SELECT * FROM wallets WHERE guild_id=? AND user_id=?",(guild_id,user_id)).fetchone()
    def add_wallet(self,guild_id:int,user_id:int,xp:int=0,coins:int=0)->None:
        self.wallet(guild_id,user_id);self.conn.execute("UPDATE wallets SET xp=xp+?,coins=coins+? WHERE guild_id=? AND user_id=?",(xp,coins,guild_id,user_id));self.conn.commit()

store=Store()
intents=discord.Intents.default();intents.members=True;intents.message_content=True;intents.voice_states=True
bot=commands.Bot(command_prefix="?",intents=intents)

def owner(member: discord.Member)->bool:
    s=store.settings(member.guild.id)
    return member.guild_permissions.administrator or member.id==member.guild.owner_id or bool(s["owner_role"] and any(r.id==s["owner_role"] for r in member.roles))
def staff(member: discord.Member)->bool:
    s=store.settings(member.guild.id)
    return owner(member) or bool(s["staff_role"] and any(r.id==s["staff_role"] for r in member.roles))
async def log(guild:discord.Guild,text:str)->None:
    channel=guild.get_channel(store.settings(guild.id)["logs_channel"])
    if isinstance(channel,discord.TextChannel): await channel.send(embed=embed(f"{E['alert']}・LOG",text))

class RoleSelect(discord.ui.RoleSelect):
    def __init__(self,field:str): super().__init__(placeholder="Selecione um cargo",min_values=1,max_values=1);self.field=field
    async def callback(self,i:discord.Interaction):
        store.conn.execute(f"UPDATE settings SET {self.field}=? WHERE guild_id=?",(self.values[0].id,i.guild_id));store.conn.commit();await i.response.send_message(f"{E['ok']} Cargo salvo.",ephemeral=True)
class ChannelSelect(discord.ui.ChannelSelect):
    def __init__(self,field:str,category:bool=False): super().__init__(placeholder="Selecione um canal",channel_types=[discord.ChannelType.category] if category else [discord.ChannelType.text],min_values=1,max_values=1);self.field=field
    async def callback(self,i:discord.Interaction):
        store.conn.execute(f"UPDATE settings SET {self.field}=? WHERE guild_id=?",(self.values[0].id,i.guild_id));store.conn.commit();await i.response.send_message(f"{E['ok']} Canal salvo.",ephemeral=True)
class OneSelectView(discord.ui.View):
    def __init__(self,item): super().__init__(timeout=120);self.add_item(item)

class TicketOpenView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Abrir ticket",emoji=E["ticket"],style=discord.ButtonStyle.secondary,custom_id="ticket:open")
    async def open_ticket(self,i:discord.Interaction,b:discord.ui.Button):
        s=store.settings(i.guild_id);cat=i.guild.get_channel(s["ticket_category"])
        if not isinstance(cat,discord.CategoryChannel): await i.response.send_message("A categoria de tickets não foi configurada.",ephemeral=True);return
        existing=store.conn.execute("SELECT 1 FROM tickets WHERE guild_id=? AND user_id=? AND status='open'",(i.guild_id,i.user.id)).fetchone()
        if existing: await i.response.send_message("Você já possui um ticket aberto.",ephemeral=True);return
        overwrites={i.guild.default_role:discord.PermissionOverwrite(view_channel=False),i.user:discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True)}
        if s["staff_role"]:
            role=i.guild.get_role(s["staff_role"])
            if role: overwrites[role]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True)
        ch=await cat.create_text_channel(f"ticket-{i.user.name}",overwrites=overwrites,reason="Ticket aberto")
        store.conn.execute("INSERT INTO tickets(guild_id,channel_id,user_id) VALUES(?,?,?)",(i.guild_id,ch.id,i.user.id));store.conn.commit()
        await ch.send(content=i.user.mention,embed=embed(f"{E['support']}・SUPORTE","Explique seu pedido. Um membro da equipe responderá em breve."),view=TicketControlView())
        await i.response.send_message(f"{E['ok']} Ticket criado: {ch.mention}",ephemeral=True)
class TicketControlView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Fechar",emoji=E["remove"],style=discord.ButtonStyle.danger,custom_id="ticket:close")
    async def close(self,i:discord.Interaction,b:discord.ui.Button):
        row=store.conn.execute("SELECT * FROM tickets WHERE channel_id=? AND status='open'",(i.channel_id,)).fetchone()
        if not row or not isinstance(i.user,discord.Member) or (i.user.id!=row["user_id"] and not staff(i.user)): await i.response.send_message("Sem permissão.",ephemeral=True);return
        store.conn.execute("UPDATE tickets SET status='closed' WHERE id=?",(row["id"],));store.conn.commit();await i.response.send_message("Ticket encerrado. Canal apagado em 5 segundos.");await asyncio.sleep(5);await i.channel.delete(reason="Ticket encerrado")

class ContentRedeemModal(discord.ui.Modal,title="Usar código"):
    code=discord.ui.TextInput(label="Código do vídeo",max_length=40)
    def __init__(self,content_id:int): super().__init__();self.content_id=content_id
    async def on_submit(self,i:discord.Interaction):
        code=str(self.code).strip().upper();row=store.conn.execute("SELECT c.*,x.file_url,x.name FROM codes c JOIN contents x ON x.id=c.content_id WHERE c.code=?",(code,)).fetchone()
        if not row or row["content_id"]!=self.content_id or row["used_by"] or not row["file_url"]: await i.response.send_message("Código inválido, usado ou expirado.",ephemeral=True);return
        try: await i.user.send(embed=embed(f"{E['gift']}・CONTEÚDO LIBERADO",f"**{row['name']}**\n\n{row['file_url']}"))
        except discord.Forbidden: await i.response.send_message("Abra sua DM e tente novamente; o código não foi usado.",ephemeral=True);return
        store.conn.execute("UPDATE codes SET used_by=?,used_at=? WHERE code=?",(i.user.id,datetime.now(timezone.utc).isoformat(),code));store.conn.commit();store.add_wallet(i.guild_id,i.user.id,xp=50,coins=50)
        await i.response.send_message(f"{E['ok']} Conteúdo enviado na sua DM.",ephemeral=True)
class ContentView(discord.ui.View):
    def __init__(self,content_id:int,video_url:str):
        super().__init__(timeout=None);self.add_item(discord.ui.Button(label="Assistir ao vídeo",emoji=E["pc"],url=video_url));self.add_item(ContentRedeemButton(content_id))
class ContentRedeemButton(discord.ui.Button):
    def __init__(self,content_id:int): super().__init__(label="Usar código",emoji=E["gift"],style=discord.ButtonStyle.secondary,custom_id=f"content:{content_id}");self.content_id=content_id
    async def callback(self,i:discord.Interaction): await i.response.send_modal(ContentRedeemModal(self.content_id))

class EventJoinView(discord.ui.View):
    def __init__(self,event_id:int):
        super().__init__(timeout=None);self.event_id=event_id
        self.children[0].custom_id=f"event:join:{event_id}"
    @discord.ui.button(label="Participar",emoji=E["gift"],style=discord.ButtonStyle.secondary,custom_id="event:join")
    async def join(self,i:discord.Interaction,b:discord.ui.Button):
        event=store.conn.execute("SELECT * FROM events WHERE id=?",(self.event_id,)).fetchone()
        if not event or event["status"]!="open": await i.response.send_message("Inscrições fechadas.",ephemeral=True);return
        total=store.conn.execute("SELECT COUNT(*) FROM event_entries WHERE event_id=?",(self.event_id,)).fetchone()[0]
        if total>=event["capacity"]: await i.response.send_message("Evento cheio.",ephemeral=True);return
        try: store.conn.execute("INSERT INTO event_entries(event_id,user_id) VALUES(?,?)",(self.event_id,i.user.id));store.conn.commit()
        except sqlite3.IntegrityError: await i.response.send_message("Você já está inscrito.",ephemeral=True);return
        store.add_wallet(i.guild_id,i.user.id,xp=40,coins=25);await i.response.send_message(f"{E['ok']} Inscrição confirmada.",ephemeral=True)

class CallLimitSelect(discord.ui.Select):
    def __init__(self): super().__init__(placeholder="Quantas pessoas na call?",custom_id="calls:limit",options=[discord.SelectOption(label=str(x),value=str(x),emoji=E["room"]) for x in [2,3,4,5,10,20]])
    async def callback(self,i:discord.Interaction): await i.response.send_message(f"Deseja criar uma call para **{self.values[0]}** pessoas?",view=CallConfirmView(int(self.values[0])),ephemeral=True)
class CallPanel(discord.ui.View):
    def __init__(self): super().__init__(timeout=None);self.add_item(CallLimitSelect())
class CallConfirmView(discord.ui.View):
    def __init__(self,limit:int): super().__init__(timeout=45);self.limit=limit
    @discord.ui.button(label="Criar call",emoji=E["room"],style=discord.ButtonStyle.success)
    async def create(self,i:discord.Interaction,b:discord.ui.Button):
        s=store.settings(i.guild_id);existing=store.conn.execute("SELECT 1 FROM temp_calls WHERE guild_id=? AND owner_id=?",(i.guild_id,i.user.id)).fetchone()
        cat=i.guild.get_channel(s["call_category"])
        if existing or not isinstance(cat,discord.CategoryChannel): await i.response.send_message("Você já tem call ou ela não foi configurada.",ephemeral=True);return
        ch=await cat.create_voice_channel(f"call-{i.user.display_name}",user_limit=self.limit,reason="Call temporária")
        store.conn.execute("INSERT INTO temp_calls(channel_id,guild_id,owner_id,created_at) VALUES(?,?,?,?)",(ch.id,i.guild_id,i.user.id,datetime.now(timezone.utc).isoformat()));store.conn.commit()
        await i.response.send_message(f"{E['ok']} Sua call foi criada: {ch.mention}",ephemeral=True)

@bot.tree.command(name="setupservidor",description="Cria a estrutura gamer completa")
async def setup_server(i:discord.Interaction):
    if not isinstance(i.user,discord.Member) or not owner(i.user): await i.response.send_message("Somente o dono.",ephemeral=True);return
    await i.response.defer(ephemeral=True)
    guild=i.guild
    layout={"INÍCIO":["boas-vindas","regras","verificacao","anuncios","videos"],"COMUNIDADE":["chat-geral","clips-e-fotos","sugestoes","eventos"],"CONTEÚDOS EXCLUSIVOS":["resgatar-codigo","conteudos-e-atualizacoes"],"SUPORTE":["abrir-ticket","status-do-suporte"],"EQUIPE":["staff-chat","logs","painel-admin"],"CALLS":["crie-sua-call"]}
    made={}
    for category_name,channels in layout.items():
        cat=discord.utils.get(guild.categories,name=category_name) or await guild.create_category(category_name)
        for name in channels:
            made[name]=discord.utils.get(cat.text_channels,name=name) or await cat.create_text_channel(name)
    s=store.settings(guild.id)
    store.conn.execute("UPDATE settings SET logs_channel=?,ticket_category=?,call_category=? WHERE guild_id=?",(made["logs"].id,discord.utils.get(guild.categories,name="SUPORTE").id,discord.utils.get(guild.categories,name="CALLS").id,guild.id));store.conn.commit()
    await made["abrir-ticket"].send(embed=embed(f"{E['ticket']}・SUPORTE","Clique abaixo para abrir seu ticket."),view=TicketOpenView())
    await made["crie-sua-call"].send(embed=embed(f"{E['room']}・CRIE SUA CALL",f"{E['clock']} Escolha o limite de pessoas. Calls vazias e calls com mais de 1 hora são removidas."),view=CallPanel())
    await i.followup.send(f"{E['ok']} Estrutura criada e painéis enviados.",ephemeral=True)

@bot.tree.command(name="config",description="Configura cargos, logs e anti-link")
@app_commands.describe(tipo="cargo_dono, cargo_staff, cargo_membro, logs, anti_link")
async def config(i:discord.Interaction,tipo:str):
    if not isinstance(i.user,discord.Member) or not owner(i.user): await i.response.send_message("Somente o dono.",ephemeral=True);return
    if tipo not in {"cargo_dono","cargo_staff","cargo_membro","logs","anti_link"}: await i.response.send_message("Use: cargo_dono, cargo_staff, cargo_membro, logs ou anti_link.",ephemeral=True);return
    if tipo=="anti_link": store.conn.execute("UPDATE settings SET anti_link=1-anti_link WHERE guild_id=?",(i.guild_id,));store.conn.commit();await i.response.send_message("Anti-link alternado.",ephemeral=True);return
    field={"cargo_dono":"owner_role","cargo_staff":"staff_role","cargo_membro":"member_role","logs":"logs_channel"}[tipo]
    await i.response.send_message("Selecione:",view=OneSelectView(RoleSelect(field) if "cargo" in tipo else ChannelSelect(field)),ephemeral=True)

@bot.tree.command(name="configticket",description="Configura categoria e cargo dos tickets")
async def config_ticket(i:discord.Interaction,cargo_staff:discord.Role,categoria:discord.CategoryChannel):
    if not isinstance(i.user,discord.Member) or not owner(i.user): await i.response.send_message("Somente o dono.",ephemeral=True);return
    store.conn.execute("UPDATE settings SET staff_role=?,ticket_category=? WHERE guild_id=?",(cargo_staff.id,categoria.id,i.guild_id));store.conn.commit();await i.response.send_message(f"{E['ok']} Tickets configurados.",ephemeral=True)
@bot.tree.command(name="ticket",description="Envia painel de tickets")
async def ticket(i:discord.Interaction):
    if not isinstance(i.user,discord.Member) or not staff(i.user): await i.response.send_message("Somente staff.",ephemeral=True);return
    await i.response.send_message(embed=embed(f"{E['ticket']}・ATENDIMENTO","Clique para abrir atendimento privado."),view=TicketOpenView())

class ContentModal(discord.ui.Modal,title="Criar conteúdo exclusivo"):
    name=discord.ui.TextInput(label="Nome");video=discord.ui.TextInput(label="Link do vídeo");file=discord.ui.TextInput(label="Link do arquivo/conteúdo");description=discord.ui.TextInput(label="Descrição",required=False,style=discord.TextStyle.paragraph)
    async def on_submit(self,i:discord.Interaction):
        cur=store.conn.execute("INSERT INTO contents(guild_id,name,description,video_url,file_url) VALUES(?,?,?,?,?)",(i.guild_id,str(self.name),str(self.description),str(self.video),str(self.file)));store.conn.commit();await i.response.send_message(f"{E['ok']} Conteúdo criado. ID: `{cur.lastrowid}`",ephemeral=True)
@bot.tree.command(name="configconteudos",description="Cria conteúdo exclusivo")
async def config_contents(i:discord.Interaction):
    if not isinstance(i.user,discord.Member) or not owner(i.user): await i.response.send_message("Somente o dono.",ephemeral=True);return
    await i.response.send_modal(ContentModal())
@bot.tree.command(name="gerarcodigos",description="Gera códigos para um conteúdo")
async def generate_codes(i:discord.Interaction,conteudo_id:int,prefixo:str,quantidade:app_commands.Range[int,1,100]=1,digitos:app_commands.Range[int,6,7]=6):
    if not isinstance(i.user,discord.Member) or not owner(i.user): await i.response.send_message("Somente o dono.",ephemeral=True);return
    content=store.conn.execute("SELECT * FROM contents WHERE id=? AND guild_id=?",(conteudo_id,i.guild_id)).fetchone()
    if not content: await i.response.send_message("Conteúdo não encontrado.",ephemeral=True);return
    prefix=re.sub(r"[^A-Z0-9]","",prefixo.upper())[:12];codes=[]
    while len(codes)<quantidade:
        code=f"{prefix}-{random.randint(0,10**digitos-1):0{digitos}d}"
        try: store.conn.execute("INSERT INTO codes(code,content_id) VALUES(?,?)",(code,conteudo_id));codes.append(code)
        except sqlite3.IntegrityError: pass
    store.conn.commit();await i.response.send_message(embed=embed(f"{E['gift']}・CÓDIGOS GERADOS","\n".join(f"`{x}`" for x in codes)),ephemeral=True)
@bot.tree.command(name="publicarconteudo",description="Publica painel de conteúdo")
async def publish_content(i:discord.Interaction,conteudo_id:int,canal:discord.TextChannel):
    if not isinstance(i.user,discord.Member) or not owner(i.user): await i.response.send_message("Somente o dono.",ephemeral=True);return
    c=store.conn.execute("SELECT * FROM contents WHERE id=? AND guild_id=?",(conteudo_id,i.guild_id)).fetchone()
    if not c: await i.response.send_message("Conteúdo não encontrado.",ephemeral=True);return
    em=embed(f"{E['gift']}・{c['name'].upper()}",f"{c['description']}\n\n{E['pc']} Assista ao vídeo, encontre o código e resgate na DM.")
    msg=await canal.send(embed=em,view=ContentView(c["id"],c["video_url"]));store.conn.execute("UPDATE contents SET channel_id=?,message_id=? WHERE id=?",(canal.id,msg.id,c["id"]));store.conn.commit();await i.response.send_message("Publicado.",ephemeral=True)

@bot.tree.command(name="daily",description="Resgata moedas diárias")
async def daily(i:discord.Interaction):
    w=store.wallet(i.guild_id,i.user.id);today=datetime.now(timezone.utc).date().isoformat()
    if w["last_daily"]==today: await i.response.send_message("Você já resgatou hoje.",ephemeral=True);return
    store.conn.execute("UPDATE wallets SET last_daily=?,coins=coins+100,xp=xp+50 WHERE guild_id=? AND user_id=?",(today,i.guild_id,i.user.id));store.conn.commit();await i.response.send_message(f"{E['ok']} +100 Coins e +50 XP.",ephemeral=True)
@bot.tree.command(name="perfil",description="Mostra seu perfil")
async def profile(i:discord.Interaction,usuario:Optional[discord.Member]=None):
    u=usuario or i.user;w=store.wallet(i.guild_id,u.id);await i.response.send_message(embed=embed(f"{E['trophy']}・PERFIL",f"{u.mention}\n{E['gift']} Coins: **{w['coins']}**\n{E['trophy']} XP: **{w['xp']}**"))
@bot.tree.command(name="ranking",description="Ranking de XP")
async def ranking(i:discord.Interaction):
    rows=store.conn.execute("SELECT user_id,xp FROM wallets WHERE guild_id=? ORDER BY xp DESC LIMIT 10",(i.guild_id,)).fetchall();text="\n".join(f"**{n}.** <@{r['user_id']}> — {r['xp']} XP" for n,r in enumerate(rows,1)) or "Sem dados.";await i.response.send_message(embed=embed(f"{E['trophy']}・RANKING",text))
@bot.tree.command(name="missoes",description="Mostra missões da comunidade")
async def missions(i:discord.Interaction): await i.response.send_message(embed=embed(f"{E['gift']}・MISSÕES",f"{E['clock']} Entre diariamente: use `/daily`.\n{E['room']} Fique em call: ganha 1 Coin e 1 XP por minuto.\n{E['gift']} Resgate conteúdo de vídeo: +50 Coins e +50 XP.\n{E['gift']} Participe de evento: +25 Coins e +40 XP."),ephemeral=True)
@bot.tree.command(name="adicionarproduto",description="Adiciona item à loja de Coins")
async def add_product(i:discord.Interaction,nome:str,custo:app_commands.Range[int,1,100000],link_entrega:str):
    if not isinstance(i.user,discord.Member) or not owner(i.user): await i.response.send_message("Somente o dono.",ephemeral=True);return
    cur=store.conn.execute("INSERT INTO products(guild_id,name,cost,file_url) VALUES(?,?,?,?)",(i.guild_id,nome,custo,link_entrega));store.conn.commit();await i.response.send_message(f"{E['ok']} Produto criado. ID: `{cur.lastrowid}`",ephemeral=True)
@bot.tree.command(name="loja",description="Mostra a loja de Coins")
async def shop(i:discord.Interaction):
    rows=store.conn.execute("SELECT * FROM products WHERE guild_id=? AND active=1 ORDER BY cost",(i.guild_id,)).fetchall()
    text="\n".join(f"`{r['id']}` • **{r['name']}** — {r['cost']} Coins" for r in rows) or "A loja ainda não possui produtos."
    await i.response.send_message(embed=embed(f"{E['gift']}・LOJA",text+"\n\nUse `/comprar produto_id` para resgatar."),ephemeral=True)
@bot.tree.command(name="comprar",description="Compra produto usando Coins")
async def buy(i:discord.Interaction,produto_id:int):
    product=store.conn.execute("SELECT * FROM products WHERE id=? AND guild_id=? AND active=1",(produto_id,i.guild_id)).fetchone();wallet=store.wallet(i.guild_id,i.user.id)
    if not product: await i.response.send_message("Produto não encontrado.",ephemeral=True);return
    if wallet["coins"]<product["cost"]: await i.response.send_message("Você não tem Coins suficientes.",ephemeral=True);return
    try: await i.user.send(embed=embed(f"{E['gift']}・COMPRA APROVADA",f"**{product['name']}**\n\n{product['file_url']}"))
    except discord.Forbidden: await i.response.send_message("Abra sua DM e tente novamente; as Coins não foram descontadas.",ephemeral=True);return
    store.conn.execute("UPDATE wallets SET coins=coins-? WHERE guild_id=? AND user_id=?",(product["cost"],i.guild_id,i.user.id));store.conn.commit();await i.response.send_message(f"{E['ok']} Compra enviada na sua DM.",ephemeral=True)

@bot.tree.command(name="configeventos",description="Cria evento da comunidade")
async def config_events(i:discord.Interaction,nome:str,descricao:str,premio:str,data_hora:str,vagas:app_commands.Range[int,1,500]=48):
    if not isinstance(i.user,discord.Member) or not owner(i.user): await i.response.send_message("Somente o dono.",ephemeral=True);return
    cur=store.conn.execute("INSERT INTO events(guild_id,name,description,prize,starts_at,capacity) VALUES(?,?,?,?,?,?)",(i.guild_id,nome,descricao,premio,data_hora,vagas));store.conn.commit();await i.response.send_message(f"{E['ok']} Evento criado. ID: `{cur.lastrowid}`",ephemeral=True)
@bot.tree.command(name="publicarevento",description="Publica painel do evento")
async def publish_event(i:discord.Interaction,event_id:int,canal:discord.TextChannel):
    if not isinstance(i.user,discord.Member) or not owner(i.user): await i.response.send_message("Somente o dono.",ephemeral=True);return
    e=store.conn.execute("SELECT * FROM events WHERE id=? AND guild_id=?",(event_id,i.guild_id)).fetchone()
    if not e: await i.response.send_message("Evento não encontrado.",ephemeral=True);return
    store.conn.execute("UPDATE events SET status='open' WHERE id=?",(event_id,));store.conn.commit();em=embed(f"{E['gift']}・{e['name'].upper()}",f"{e['description']}\n\n{E['trophy']} Prêmio: **{e['prize']}**\n{E['clock']} Data: **{e['starts_at']}**\n{E['staff']} Vagas: **0/{e['capacity']}**")
    msg=await canal.send(embed=em,view=EventJoinView(event_id));store.conn.execute("UPDATE events SET channel_id=?,message_id=? WHERE id=?",(canal.id,msg.id,event_id));store.conn.commit();await i.response.send_message("Evento publicado.",ephemeral=True)

@bot.tree.command(name="configcalls",description="Configura calls temporárias")
async def config_calls(i:discord.Interaction,categoria:discord.CategoryChannel,tempo_minutos:app_commands.Range[int,10,180]=60):
    if not isinstance(i.user,discord.Member) or not owner(i.user): await i.response.send_message("Somente o dono.",ephemeral=True);return
    store.conn.execute("UPDATE settings SET call_category=?,call_minutes=? WHERE guild_id=?",(categoria.id,tempo_minutos,i.guild_id));store.conn.commit();await i.response.send_message("Calls configuradas.",ephemeral=True)
@bot.tree.command(name="painelcalls",description="Envia painel para criar call")
async def calls_panel(i:discord.Interaction):
    if not isinstance(i.user,discord.Member) or not staff(i.user): await i.response.send_message("Somente staff.",ephemeral=True);return
    await i.response.send_message(embed=embed(f"{E['room']}・CRIE SUA CALL",f"{E['clock']} Escolha o limite e confirme. Calls vazias ou vencidas são apagadas."),view=CallPanel())

@bot.tree.command(name="ia",description="Pergunte à IA da comunidade")
async def ai(i:discord.Interaction,pergunta:str):
    key=os.getenv("GEMINI_API_KEY","").strip();model=os.getenv("GEMINI_MODEL","gemini-2.0-flash").strip()
    if not key: await i.response.send_message("IA ainda não configurada pelo dono.",ephemeral=True);return
    await i.response.defer()
    url=f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url,json={"contents":[{"parts":[{"text":pergunta}]}]}) as resp: data=await resp.json()
        answer=data["candidates"][0]["content"]["parts"][0]["text"][:1900]
        await i.followup.send(embed=embed(f"{E['pc']}・IA",answer))
    except Exception: await i.followup.send("Não consegui responder agora. Confira a chave Gemini e o modelo.")

@bot.event
async def on_message(message:discord.Message):
    if message.author.bot or not message.guild:return
    if isinstance(message.author,discord.Member) and not staff(message.author) and store.settings(message.guild.id)["anti_link"]:
        if re.search(r"(?:https?://|discord\.gg/|www\.)",message.content,re.I):
            try: await message.delete();await message.channel.send(f"{E['block']} {message.author.mention}, links não são permitidos aqui.",delete_after=6)
            except discord.HTTPException: pass
            return
    store.add_wallet(message.guild.id,message.author.id,xp=1,coins=1);await bot.process_commands(message)
@bot.event
async def on_voice_state_update(member:discord.Member,before:discord.VoiceState,after:discord.VoiceState):
    if before.channel and before.channel.id in [r["channel_id"] for r in store.conn.execute("SELECT channel_id FROM temp_calls").fetchall()] and not before.channel.members:
        store.conn.execute("DELETE FROM temp_calls WHERE channel_id=?",(before.channel.id,));store.conn.commit();await before.channel.delete(reason="Call vazia")
@tasks.loop(minutes=1)
async def clean_calls():
    now=datetime.now(timezone.utc)
    for row in store.conn.execute("SELECT * FROM temp_calls").fetchall():
        guild=bot.get_guild(row["guild_id"]);ch=guild.get_channel(row["channel_id"]) if guild else None
        if not isinstance(ch,discord.VoiceChannel): continue
        age=now-datetime.fromisoformat(row["created_at"])
        if age>=timedelta(minutes=store.settings(guild.id)["call_minutes"]):
            for m in ch.members:
                try: await m.move_to(None,reason="Tempo da call esgotado")
                except discord.HTTPException: pass
            store.conn.execute("DELETE FROM temp_calls WHERE channel_id=?",(ch.id,));store.conn.commit();await ch.delete(reason="Tempo esgotado")
@bot.event
async def on_ready():
    if not clean_calls.is_running():clean_calls.start()
    bot.add_view(TicketOpenView());bot.add_view(TicketControlView());bot.add_view(CallPanel())
    for c in store.conn.execute("SELECT id,video_url FROM contents WHERE active=1 AND message_id IS NOT NULL").fetchall():bot.add_view(ContentView(c["id"],c["video_url"]))
    for e in store.conn.execute("SELECT id FROM events WHERE status='open' AND message_id IS NOT NULL").fetchall():bot.add_view(EventJoinView(e["id"]))
    await bot.tree.sync();print(f"Conectado como {bot.user}")

token=os.getenv("DISCORD_TOKEN","").strip().strip('"').strip("'")
if not token: raise RuntimeError("Configure DISCORD_TOKEN no .env ou Railway")
bot.run(token)
