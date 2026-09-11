"""
Lunar Market - Bot de Tickets (SQLite) - bot.py

Características:
- Lee token desde DISCORD_TOKEN (env var)
- Persistencia en SQLite (tickets.db)
- Comandos con prefijo: !ticket setup/create/list/claim/close/add/remove/info/rename/panel/transcript
- Panel con botones en lugar de reacciones
- Botones en cada ticket: Reclamar y Cerrar
"""

import os
import json
import asyncio
from datetime import datetime
from typing import Optional

import aiosqlite
import discord
from discord.ext import commands

# ----- Config y archivos -----
CONFIG_SAMPLE = "config.sample.json"
DB_PATH = os.getenv("TICKETS_DB", "tickets.db")
BOT_PREFIX = "!"

# Cargar config sample y opcional config.json
def load_config():
    cfg = {}
    try:
        with open(CONFIG_SAMPLE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        cfg = {}
    # si hay config.json, usa y sobrescribe
    if os.path.exists("config.json"):
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                cfg2 = json.load(f)
                cfg.update(cfg2)
        except Exception:
            pass
    return cfg

cfg = load_config()

# ----- Helper DB -----
async def ensure_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            channel_id INTEGER,
            owner_id INTEGER,
            category TEXT,
            status TEXT,
            claimed_by INTEGER,
            reason TEXT,
            created_at TEXT,
            closed_at TEXT,
            close_reason TEXT
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)
        await db.commit()

async def set_meta(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("REPLACE INTO meta(key,value) VALUES(?,?)", (key, value))
        await db.commit()

async def get_meta(key: str) -> Optional[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value FROM meta WHERE key=?", (key,))
        row = await cur.fetchone()
        return row[0] if row else None

# ----- Utils -----
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix=BOT_PREFIX, intents=intents, help_command=commands.DefaultHelpCommand(no_category="Comandos"))

def is_staff(member: discord.Member) -> bool:
    # Revisar role IDs desde config y vars
    try:
        role_ids = cfg.get("staff_role_ids", []) or []
        for rid in role_ids:
            role = member.guild.get_role(int(rid))
            if role and role in member.roles:
                return True
    except Exception:
        pass
    if member.guild_permissions.administrator:
        return True
    return False

# ----- Ticket logic -----
async def create_ticket_record(guild_id, channel_id, owner_id, category, reason):
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO tickets (guild_id, channel_id, owner_id, category, status, claimed_by, reason, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (guild_id, channel_id, owner_id, category, 'open', None, reason or '', now)
        )
        await db.commit()
        return cur.lastrowid

async def get_ticket_by_channel(channel_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT * FROM tickets WHERE channel_id=?", (channel_id,))
        row = await cur.fetchone()
        return row

async def list_tickets(guild_id, where_clause=None, params=()):
    query = "SELECT id,owner_id,channel_id,category,status,claimed_by,created_at FROM tickets WHERE guild_id=?"
    params = (guild_id,) + tuple(params)
    if where_clause:
        query += " AND " + where_clause
    query += " ORDER BY id DESC"
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(query, params)
        rows = await cur.fetchall()
        return rows

# ----- UI Views (Buttons) -----
class TicketControlView(discord.ui.View):
    def __init__(self, ticket_id: int, *, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)
        self.ticket_id = ticket_id

    @discord.ui.button(label="Reclamar", style=discord.ButtonStyle.primary, custom_id="ticket_claim")
    async def claim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if staff
        member = interaction.user
        if not is_staff(member):
            await interaction.response.send_message("Solo staff puede reclamar tickets.", ephemeral=True)
            return
        # find ticket by channel
        ticket = await get_ticket_by_channel(interaction.channel.id)
        if not ticket:
            await interaction.response.send_message("Este canal no parece ser un ticket.", ephemeral=True)
            return
        if ticket[6]:
            await interaction.response.send_message("Este ticket ya fue reclamado.", ephemeral=True)
            return
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE tickets SET claimed_by=? WHERE id=?", (member.id, ticket[0]))
            await db.commit()
        await interaction.response.send_message(f"✅ {member.mention} reclamó este ticket.", ephemeral=False)

    @discord.ui.button(label="Cerrar ticket", style=discord.ButtonStyle.danger, custom_id="ticket_close")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Allow owner, staff or admin to close
        ticket = await get_ticket_by_channel(interaction.channel.id)
        if not ticket:
            await interaction.response.send_message("Este canal no parece ser un ticket.", ephemeral=True)
            return
        author = interaction.user
        if author.id != ticket[3] and not is_staff(author) and not author.guild_permissions.administrator:
            await interaction.response.send_message("Solo el creador, staff o admin puede cerrar este ticket.", ephemeral=True)
            return
        reason = "Cerrado vía botón"
        closed_at = datetime.utcnow().isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE tickets SET status='closed', closed_at=?, close_reason=? WHERE id=?", (closed_at, reason, ticket[0]))
            await db.commit()
        try:
            # rename channel
            await interaction.channel.edit(name=f"closed-{interaction.channel.name}")
            owner = interaction.guild.get_member(ticket[3])
            if owner:
                await interaction.channel.set_permissions(owner, send_messages=False, read_message_history=True, view_channel=True)
        except Exception:
            pass
        await send_transcript_to_logs(interaction.channel, ticket)
        await interaction.response.send_message("🔒 Ticket cerrado.", ephemeral=False)
        # disable buttons
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

class TicketPanelView(discord.ui.View):
    def __init__(self, categories: dict, *, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)
        self.categories = categories
        # create a button per category (max 25 buttons per view)
        for key, info in categories.items():
            label = str(key)
            emoji = info.get('emoji')
            # discord.Button emoji expects Emoji/PartialEmoji or str, but sending custom emoji as label is fine too
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, custom_id=f"panel_cat:{key}")
            # attach callback
            async def make_callback(k):
                async def callback(interaction: discord.Interaction):
                    await self.handle_create(interaction, k)
                return callback
            # bind callback
            btn.callback = asyncio.get_event_loop().run_until_complete(make_callback(key))
            self.add_item(btn)

    async def handle_create(self, interaction: discord.Interaction, category_key: str):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        user = interaction.user
        # reuse create logic (similar to cmd_create)
        cat = category_key
        reason = f"Creado desde panel (botón) por {user}"
        # category object
        cat_obj = None
        cat_id = os.getenv('TICKET_CATEGORY_ID') or cfg.get('ticket_category_id')
        if cat_id:
            try:
                cat_obj = guild.get_channel(int(cat_id))
                if not isinstance(cat_obj, discord.CategoryChannel):
                    cat_obj = None
            except Exception:
                cat_obj = None
        if not cat_obj:
            cat_name = cfg.get('ticket_category_name','Lunar Market Tickets')
            cat_obj = discord.utils.get(guild.categories, name=cat_name)
            if not cat_obj:
                cat_obj = await guild.create_category(cat_name, reason='Creando categoría para tickets')
        # permissions
        overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False), guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)}
        for rid in cfg.get('staff_role_ids',[]) or []:
            try:
                role = guild.get_role(int(rid))
                if role:
                    overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
            except Exception:
                pass
        overwrites[user] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        safe_user = user.name.lower().replace(' ','-')[:20]
        channel = await guild.create_text_channel(f"ticket-{safe_user}", overwrites=overwrites, category=cat_obj, topic=f"Ticket {cat} creado por {user}")
        tid = await create_ticket_record(guild.id, channel.id, user.id, cat, reason)
        tag_role = os.getenv('TAG_ON_CREATE_ROLE_ID') or cfg.get('tag_on_create_role_id')
        mention = f"<@&{tag_role}>" if tag_role else ''
        cat_info = cfg.get('categories',{}).get(cat,{})
        embed = discord.Embed(title=f"{cat_info.get('emoji','🛎️')} Ticket #{tid} — {cat}", description=f"{cat_info.get('desc','')}\n\n• Creado por: {user.mention}\n• Razón: {reason}", color=0x7B68EE, timestamp=datetime.utcnow())
        control_view = TicketControlView(tid)
        await channel.send(content=f"{mention} {user.mention}", embed=embed, view=control_view)
        try:
            await user.send(f"✅ Tu ticket fue creado en **{guild.name}**: {channel.mention}")
        except Exception:
            pass
        await interaction.followup.send(f"✅ Ticket creado: {channel.mention}", ephemeral=True)

# ----- Bot events & commands -----
@bot.event
async def on_ready():
    await ensure_db()
    print(f"Conectado como {bot.user} (id: {bot.user.id})")
    # Si GUILD_ID está configurada, sincronizar app commands localmente para pruebas
    GUILD_ID = os.getenv("GUILD_ID")
    if GUILD_ID:
        try:
            bot.tree.copy_global_to(guild=discord.Object(id=int(GUILD_ID)))
            await bot.tree.sync(guild=discord.Object(id=int(GUILD_ID)))
            print(f"Sincronizados comandos con guild {GUILD_ID}")
        except Exception as e:
            print("No se pudo sincronizar comandos de aplicación:", e)

# Comando raíz !ticket
@bot.command(name="ticket")
@commands.guild_only()
async def ticket_root(ctx, sub: Optional[str] = None, *args):
    if not sub:
        return await ctx.send_help("ticket")
    sub = sub.lower()
    if sub == "setup":
        await cmd_setup(ctx)
    elif sub == "create":
        await cmd_create(ctx, *args)
    elif sub == "close":
        await cmd_close(ctx, *args)
    elif sub == "claim":
        await cmd_claim(ctx)
    elif sub == "add":
        await cmd_add(ctx, *args)
    elif sub == "remove":
        await cmd_remove(ctx, *args)
    elif sub == "list":
        await cmd_list(ctx, *args)
    elif sub == "info":
        await cmd_info(ctx)
    elif sub == "rename":
        await cmd_rename(ctx, *args)
    elif sub == "panel":
        await cmd_panel(ctx)
    elif sub == "transcript":
        await cmd_transcript(ctx)
    else:
        await ctx.send("Subcomando desconocido. Usa `!ticket` para ver ayuda.")

# Implementación de subcomandos (modulares)
async def cmd_setup(ctx: commands.Context):
    if not ctx.author.guild_permissions.administrator:
        return await ctx.send("Necesitas permisos de administrador para ejecutar esto.")
    guild = ctx.guild
    # crear categoría (usar env var o config)
    cat = None
    cat_id = os.getenv("TICKET_CATEGORY_ID") or cfg.get("ticket_category_id")
    if cat_id:
        try:
            cat = guild.get_channel(int(cat_id))
            if not isinstance(cat, discord.CategoryChannel):
                cat = None
        except Exception:
            cat = None
    if not cat:
        cname = cfg.get("ticket_category_name", "Lunar Market Tickets")
        cat = discord.utils.get(guild.categories, name=cname)
        if not cat:
            cat = await guild.create_category(cname, reason="Setup de tickets Lunar Market")
    # crear canal panel
    panel_name = cfg.get("panel_channel_name", "🎫-crear-ticket") if cfg.get("panel_channel_name") else "🎫-crear-ticket"
    panel_channel = discord.utils.get(guild.text_channels, name=panel_name)
    if not panel_channel:
        panel_channel = await guild.create_text_channel(panel_name, category=cat, reason="Panel de tickets")
    # construir embed del panel
    cats = cfg.get("categories", {})
    lines = [f"{v.get('emoji','🛎️')} **{k}** — {v.get('desc','')}" for k,v in cats.items()]
    embed = discord.Embed(title="🎟️ Lunar Market — Crear un Ticket", description="\n".join(lines), color=0x6A5ACD)
    embed.set_footer(text="Pulsa el botón correspondiente para crear un ticket.")
    view = TicketPanelView(cats)
    msg = await panel_channel.send(embed=embed, view=view)
    # guardar meta
    await set_meta('panel_message_id', str(msg.id))
    await set_meta('panel_channel_id', str(panel_channel.id))
    await ctx.send(f"Panel creado en {panel_channel.mention} con botones.")

async def cmd_create(ctx: commands.Context, *args):
    if len(args) == 0:
        return await ctx.send("Uso: `!ticket create <categoria> [razón]` — escribe `!ticket create categorias` para ver las disponibles.`")
    cat = args[0].lower()
    if cat == 'categorias':
        cats = cfg.get('categories', {})
        lines = [f"{v.get('emoji','')} **{k}** — {v.get('desc','')}" for k,v in cats.items()]
        return await ctx.send("Categorías disponibles:\n" + "\n".join(lines))
    if cat not in cfg.get('categories', {}):
        return await ctx.send("Categoría inválida. Usa `!ticket create categorias` para ver las disponibles.")
    reason = " ".join(args[1:]) if len(args) > 1 else None
    # crear canal
    guild = ctx.guild
    # category
    cat_obj = None
    cat_id = os.getenv('TICKET_CATEGORY_ID') or cfg.get('ticket_category_id')
    if cat_id:
        try:
            cat_obj = guild.get_channel(int(cat_id))
            if not isinstance(cat_obj, discord.CategoryChannel):
                cat_obj = None
        except Exception:
            cat_obj = None
    if not cat_obj:
        cat_name = cfg.get('ticket_category_name','Lunar Market Tickets')
        cat_obj = discord.utils.get(guild.categories, name=cat_name)
        if not cat_obj:
            cat_obj = await guild.create_category(cat_name, reason='Creando categoría para tickets')
    # permissions
    overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False), guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)}
    for rid in cfg.get('staff_role_ids',[]) or []:
        try:
            role = guild.get_role(int(rid))
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        except Exception:
            pass
    overwrites[ctx.author] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
    safe_user = ctx.author.name.lower().replace(' ','-')[:20]
    channel = await guild.create_text_channel(f"ticket-{safe_user}", overwrites=overwrites, category=cat_obj, topic=f"Ticket {cat} creado por {ctx.author}")
    tid = await create_ticket_record(guild.id, channel.id, ctx.author.id, cat, reason)
    # mensaje inicial con botones
    tag_role = os.getenv('TAG_ON_CREATE_ROLE_ID') or cfg.get('tag_on_create_role_id')
    mention = f"<@&{tag_role}>" if tag_role else ''
    cat_info = cfg.get('categories',{}).get(cat,{})
    embed = discord.Embed(title=f"{cat_info.get('emoji','🛎️')} Ticket #{tid} — {cat}", description=f"{cat_info.get('desc','')}\n\n• Creado por: {ctx.author.mention}\n• Razón: {reason or 'No especificada'}", color=0x7B68EE, timestamp=datetime.utcnow())
    control_view = TicketControlView(tid)
    await channel.send(content=f"{mention} {ctx.author.mention}", embed=embed, view=control_view)
    await ctx.send(f"Ticket creado: {channel.mention}")

async def cmd_claim(ctx: commands.Context):
    if not is_staff(ctx.author):
        return await ctx.send("Solo el staff puede reclamar tickets.")
    ticket = await get_ticket_by_channel(ctx.channel.id)
    if not ticket:
        return await ctx.send("Este canal no parece ser un ticket.")
    if ticket[6]:
        return await ctx.send("Este ticket ya fue reclamado.")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tickets SET claimed_by=? WHERE id=?", (ctx.author.id, ticket[0]))
        await db.commit()
    await ctx.send(f"✅ {ctx.author.mention} reclamó este ticket.")

async def cmd_close(ctx: commands.Context, *args):
    ticket = await get_ticket_by_channel(ctx.channel.id)
    if not ticket:
        return await ctx.send("Este canal no parece ser un ticket.")
    if ctx.author.id != ticket[3] and not is_staff(ctx.author) and not ctx.author.guild_permissions.administrator:
        return await ctx.send("Solo el creador del ticket, staff o administrador puede cerrarlo.")
    reason = " ".join(args) if args else "Cerrado"
    closed_at = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tickets SET status='closed', closed_at=?, close_reason=? WHERE id=?", (closed_at, reason, ticket[0]))
        await db.commit()
    try:
        await ctx.channel.edit(name=f"closed-{ctx.channel.name}")
        owner = ctx.guild.get_member(ticket[3])
        if owner:
            await ctx.channel.set_permissions(owner, send_messages=False, read_message_history=True, view_channel=True)
        await ctx.send(f"🔒 Ticket cerrado. Razón: {reason}")
    except Exception:
        await ctx.send("Ticket marcado como cerrado (no se pudo renombrar/ajustar permisos).")
    # transcript
    await send_transcript_to_logs(ctx.channel, ticket)

async def cmd_add(ctx: commands.Context, *args):
    if not args:
        return await ctx.send("Uso: `!ticket add @usuario`")
    ticket = await get_ticket_by_channel(ctx.channel.id)
    if not ticket:
        return await ctx.send("Este canal no parece ser un ticket.")
    if ctx.author.id != ticket[3] and not is_staff(ctx.author) and not ctx.author.guild_permissions.administrator:
        return await ctx.send("Solo el creador, staff o admin puede añadir usuarios.")
    member = ctx.message.mentions[0] if ctx.message.mentions else None
    if not member:
        return await ctx.send("Menciona al usuario que quieres añadir.")
    await ctx.channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True)
    await ctx.send(f"➕ {member.mention} fue añadido al ticket.")

async def cmd_remove(ctx: commands.Context, *args):
    if not args:
        return await ctx.send("Uso: `!ticket remove @usuario`")
    ticket = await get_ticket_by_channel(ctx.channel.id)
    if not ticket:
        return await ctx.send("Este canal no parece ser un ticket.")
    if ctx.author.id != ticket[3] and not is_staff(ctx.author) and not ctx.author.guild_permissions.administrator:
        return await ctx.send("Solo el creador, staff o admin puede remover usuarios.")
    member = ctx.message.mentions[0] if ctx.message.mentions else None
    if not member:
        return await ctx.send("Menciona al usuario que quieres remover.")
    await ctx.channel.set_permissions(member, overwrite=None)
    await ctx.send(f"➖ {member.mention} fue removido del ticket.")

async def cmd_list(ctx: commands.Context, *args):
    # soporta: list (open), list all, list closed, list mine, list claimed, list category <name>
    is_staff_user = is_staff(ctx.author) or ctx.author.guild_permissions.administrator
    args = list(args)
    filter_mode = 'open'
    page = 1
    category_filter = None
    if args:
        if args[0].lower() in ('all','open','closed','mine','claimed'):
            filter_mode = args[0].lower()
            args = args[1:]
        elif args[0].lower() == 'category' and len(args) >= 2:
            filter_mode = 'category'
            category_filter = args[1].lower()
            args = args[2:]
        if len(args) >= 2 and args[0].lower() == 'page':
            try:
                page = max(1, int(args[1]))
            except Exception:
                page = 1
    if filter_mode in ('all','closed','claimed','category') and not is_staff_user:
        return await ctx.send('Solo staff o administradores pueden usar ese filtro.')
    where = None
    params = []
    if filter_mode == 'open':
        where = "status='open'"
    elif filter_mode == 'closed':
        where = "status='closed'"
    elif filter_mode == 'claimed':
        where = "claimed_by IS NOT NULL"
    elif filter_mode == 'mine':
        where = "owner_id=?"
        params = [ctx.author.id]
    elif filter_mode == 'category':
        where = "LOWER(category)=?"
        params = [category_filter]
    rows = await list_tickets(ctx.guild.id, where, params)
    if not rows:
        return await ctx.send('No se encontraron tickets con ese filtro.')
    per_page = 10
    total_pages = (len(rows) + per_page - 1) // per_page
    if page > total_pages:
        page = total_pages
    start = (page-1)*per_page
    end = start+per_page
    page_rows = rows[start:end]
    lines = []
    for r in page_rows:
        tid, owner_id, channel_id, category, status, claimed_by, created_at = r[0], r[1], r[2], r[4], r[5], r[6], r[8] if len(r)>8 else ''
        owner = ctx.guild.get_member(owner_id)
        ch = ctx.guild.get_channel(channel_id)
        claimed = ''
        if claimed_by:
            claimer = ctx.guild.get_member(claimed_by)
            claimed = f' • Reclamado por {claimer.mention if claimer else claimed_by}'
        status_emoji = '🟢' if status=='open' else '🔴'
        lines.append(f"{status_emoji} #{tid} — **{category}** — {owner.mention if owner else owner_id} — {ch.mention if ch else 'canal eliminado'}{claimed}")
    embed = discord.Embed(title='📋 Lista de tickets', color=0x6A5ACD)
    embed.description = '\n'.join(lines)
    embed.set_footer(text=f'Página {page}/{total_pages} • filtro: {filter_mode}')
    await ctx.send(embed=embed)

async def cmd_info(ctx: commands.Context):
    ticket = await get_ticket_by_channel(ctx.channel.id)
    if not ticket:
        return await ctx.send('Este canal no parece ser un ticket.')
    # ticket row mapping recall
    tid = ticket[0]
    owner = ctx.guild.get_member(ticket[3])
    claimer = ctx.guild.get_member(ticket[6]) if ticket[6] else None
    embed = discord.Embed(title=f'ℹ️ Info Ticket #{tid}', color=0x00FFAA)
    embed.add_field(name='Categoría', value=ticket[4] or 'N/A', inline=True)
    embed.add_field(name='Estado', value=ticket[5] or 'N/A', inline=True)
    embed.add_field(name='Creador', value=owner.mention if owner else str(ticket[3]), inline=True)
    embed.add_field(name='Reclamado por', value=claimer.mention if claimer else 'Sin reclamar', inline=True)
    embed.add_field(name='Razón', value=ticket[7] or 'N/A', inline=False)
    embed.add_field(name='Creado', value=ticket[8] or 'N/A', inline=True)
    if ticket[5]=='closed':
        embed.add_field(name='Cerrado', value=ticket[9] or 'N/A', inline=True)
        embed.add_field(name='Motivo cierre', value=ticket[10] or 'N/A', inline=False)
    await ctx.send(embed=embed)

async def cmd_rename(ctx: commands.Context, *args):
    if not args:
        return await ctx.send('Uso: `!ticket rename nuevo-nombre`')
    ticket = await get_ticket_by_channel(ctx.channel.id)
    if not ticket:
        return await ctx.send('Este canal no parece ser un ticket.')
    if ctx.author.id != ticket[3] and not is_staff(ctx.author) and not ctx.author.guild_permissions.administrator:
        return await ctx.send('Solo el creador, staff o admin puede renombrarlo.')
    new_name = '-'.join(args)
    try:
        await ctx.channel.edit(name=new_name)
        await ctx.send(f'✏️ Canal renombrado a `{new_name}`.')
    except Exception as e:
        await ctx.send(f'No pude renombrar el canal: {e}')

async def cmd_transcript(ctx: commands.Context):
    ticket = await get_ticket_by_channel(ctx.channel.id)
    if not ticket:
        return await ctx.send('Este canal no parece ser un ticket.')
    await ctx.send('Generando transcript...')
    await send_transcript_to_logs(ctx.channel, ticket, notify_channel=True)

async def send_transcript_to_logs(channel: discord.TextChannel, ticket_row, notify_channel=False):
    log_id = os.getenv('LOG_CHANNEL_ID') or None
    if not log_id:
        if notify_channel:
            await channel.send('No hay canal de logs configurado. Configura LOG_CHANNEL_ID en las env vars.')
        return
    guild = channel.guild
    log_channel = guild.get_channel(int(log_id))
    if not log_channel:
        if notify_channel:
            await channel.send('Canal de logs no encontrado en el servidor.')
        return
    msgs = []
    async for m in channel.history(limit=None, oldest_first=True):
        ts = m.created_at.strftime('%Y-%m-%d %H:%M:%S')
        author = f"{m.author} ({m.author.id})"
        content = m.content or ''
        if m.attachments:
            content += '\n' + ' '.join(a.url for a in m.attachments)
        msgs.append(f"[{ts}] {author}: {content}")
    transcript_text = '\n'.join(msgs)[:1900000]
    filename = f"transcript-ticket-{ticket_row[0]}.txt"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(transcript_text)
    await log_channel.send(f"🗂️ Transcript del ticket #{ticket_row[0]} ({ticket_row[4]})", file=discord.File(filename))
    try:
        os.remove(filename)
    except Exception:
        pass
    if notify_channel:
        await channel.send(f"Transcript enviado a {log_channel.mention}.")

# Listener de reacciones (ya no necesario, pero mantenido para compatibilidad)
@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    # legacy support: ignore panel reactions as we use buttons
    return

# Run
if __name__ == '__main__':
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        print('Error: define la variable de entorno DISCORD_TOKEN con el token del bot.')
        exit(1)
    bot.run(TOKEN)
