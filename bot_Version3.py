#!/usr/bin/env python3
"""
Lunar Market - Sistema de Tickets (actualizado)

Cambios importantes para ti:
- Añadí los emojis personalizados que pediste.
- Los tickets se crean en la categoría con ID 1548068709443305583 si existe.
- Cuando se crea un ticket se etiqueta al rol 1451204772672831564.
- Soporta staff tanto por nombre (staff_roles) como por ID (staff_role_ids).
- Mensajes embellecidos con embeds y mejor formato.
- Panel de reacciones usa los emojis configurados en config.json.

Requisitos:
- python 3.9+
- discord.py>=2.0.0
"""
import os
import json
import asyncio
from datetime import datetime
from typing import Optional

import discord
from discord.ext import commands

# Intents
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

BOT_PREFIX = "!"
DATA_FILE = "tickets.json"
CONFIG_FILE = "config.json"

bot = commands.Bot(command_prefix=BOT_PREFIX, intents=intents, help_command=commands.DefaultHelpCommand(no_category="Comandos"))

# --- Utilities para archivo JSON ---
def ensure_files():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_id": 0, "tickets": {}}, f, indent=2, ensure_ascii=False)
    if not os.path.exists(CONFIG_FILE):
        sample = {
            "ticket_category_name": "Lunar Market Tickets",
            # Si quieres forzar una categoría existente, coloca aquí su ID (int); si es null se usará el nombre
            "ticket_category_id": 1548068709443305583,
            "panel_channel_name": "🎫-crear-ticket",
            "log_channel_id": None,
            # staff roles por nombre (legacy) y por id (más fiable)
            "staff_roles": ["Staff", "Moderador"],
            "staff_role_ids": [1451204772672831564],
            "tag_on_create_role_id": 1451204772672831564,
            "categories": {
                "soporte": {
                    "emoji": "🛎️",
                    "desc": "Ayuda general con compras, problemas técnicos o preguntas sobre la tienda."
                },
                "tienda": {
                    "emoji": "🛍️",
                    "desc": "Consultas relacionadas con productos, pagos, envíos o inventario."
                },
                "postulaciones": {
                    "emoji": "🧑‍💼",
                    "desc": "Formularios y seguimiento para postulaciones a staff."
                },
                "reclaim": {
                    "emoji": "🔁",
                    "desc": "Reclamaciones / devolución de artículos o errores en entregas."
                },
                "reporte": {
                    "emoji": "🚨",
                    "desc": "Reportes de usuarios, fraudes o comportamientos inapropiados."
                },
                "regalo": {
                    "emoji": "<:regalo_cherrybox:1488944546510409911>",
                    "desc": "Consultas sobre cajas/regalos."
                },
                "mantenimiento": {
                    "emoji": "<:md_mantenimiento:1489283103242457261>",
                    "desc": "Avisos o dudas sobre mantenimientos."
                },
                "dueo": {
                    "emoji": "<:Dueo:1488948495447757021>",
                    "desc": "Contacto directo con responsables / dueños."
                },
                "peruano": {
                    "emoji": "<:PERUANO:1488948529891381268>",
                    "desc": "Consultas o eventos relacionados con la comunidad Peruana."
                },
                "viperfinder": {
                    "emoji": "<:viperfinder_viperfinde_558:1489283055746027760>",
                    "desc": "Soporte para ViperFinder / herramientas relacionadas."
                }
            },
            "panel_message_id": None,
            "panel_channel_id": None
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(sample, f, indent=2, ensure_ascii=False)


def load_data():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def is_staff(member: discord.Member, cfg) -> bool:
    # Comprueba role IDs primero (más fiable), luego nombres
    try:
        role_ids = cfg.get("staff_role_ids", []) or []
        for rid in role_ids:
            role = member.guild.get_role(int(rid))
            if role and role in member.roles:
                return True
    except Exception:
        pass
    for rname in cfg.get("staff_roles", []):
        if discord.utils.get(member.roles, name=rname):
            return True
    # permisos administrativos también cuentan
    if member.guild_permissions.administrator:
        return True
    return False


# --- Cog de tickets ---
class Ticket(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        ensure_files()
        self.data = load_data()
        self.cfg = load_config()

    # helper para actualizar archivos en disco
    def _save(self):
        save_data(self.data)
        save_config(self.cfg)

    async def create_ticket_channel(self, guild: discord.Guild, user: discord.Member, category_key: str, reason: Optional[str]):
        # Obtener category por ID si está configurada, si no por nombre o crearla
        cfg = self.cfg
        category = None
        cat_id = cfg.get("ticket_category_id")
        if cat_id:
            category = guild.get_channel(int(cat_id))
            # validar que sea CategoryChannel
            if category and not isinstance(category, discord.CategoryChannel):
                category = None
        if not category:
            category_name = cfg.get("ticket_category_name", "Lunar Market Tickets")
            category = discord.utils.get(guild.categories, name=category_name)
            if not category:
                category = await guild.create_category(category_name, reason="Creando categoría de tickets para Lunar Market")

        # contador de tickets
        self.data = load_data()
        last = self.data.get("last_id", 0) + 1
        self.data["last_id"] = last

        # nombre del canal
        safe_user = user.name.lower().replace(" ", "-")[:20]
        channel_name = f"ticket-{last}-{safe_user}"

        # permisos: nadie excepto staff y user y el bot
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        }

        # agregar roles del staff (por nombres)
        for rname in cfg.get("staff_roles", []):
            role = discord.utils.get(guild.roles, name=rname)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        # agregar roles del staff (por IDs)
        for rid in cfg.get("staff_role_ids", []) or []:
            try:
                role_obj = guild.get_role(int(rid))
                if role_obj:
                    overwrites[role_obj] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
            except Exception:
                pass

        # permitir acceso al autor
        overwrites[user] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        channel = await guild.create_text_channel(channel_name, overwrites=overwrites, category=category, topic=f"Ticket {last} - {category_key} - creado por {user} ")

        # Guardar la info
        ticket_obj = {
            "id": last,
            "guild_id": guild.id,
            "channel_id": channel.id,
            "owner_id": user.id,
            "category": category_key,
            "status": "open",
            "created_at": datetime.utcnow().isoformat(),
            "claimed_by": None,
            "reason": reason or "",
            "messages": []
        }
        self.data["tickets"][str(last)] = ticket_obj
        self._save()

        # Mensaje inicial bonito en el canal con mención al rol de staff
        tag_role_id = cfg.get("tag_on_create_role_id")
        tag_text = f"<@&{tag_role_id}>" if tag_role_id else ""
        cat_info = cfg.get("categories", {}).get(category_key, {})
        desc = cat_info.get("desc", "")
        emoji = cat_info.get("emoji", "")
        embed = discord.Embed(
            title=f"{emoji} Ticket #{last} — {category_key}",
            description=f"{desc}\n\n• Creado por: {user.mention}\n• Razón: {reason or 'No especificada'}",
            color=0x7B68EE,
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="Equipo Lunar Market • Responderemos lo antes posible")
        # imagen/thumbnail opcional: puedes añadir una url si quieres
        try:
            await channel.send(content=f"{tag_text} {user.mention}", embed=embed)
            await channel.send("Para cerrar el ticket escribe `!ticket close <motivo>` • Para reclamar usa `!ticket claim` • Para añadir/quitar usuarios `!ticket add/remove @user`")
        except Exception:
            # fallback sin embed
            await channel.send(f"{tag_text} {user.mention} • Tu ticket ha sido creado en {channel.mention}")

        return channel, ticket_obj

    # comando setup para crear panel y categorías (mejorado)
    @commands.command(name="ticket")
    @commands.guild_only()
    async def ticket_root(self, ctx, sub: Optional[str] = None, *args):
        """Comando raíz: usa !ticket setup / create / close / claim / add / remove / list / info / rename / panel / transcript"""
        if not sub:
            return await ctx.send_help("ticket")
        sub = sub.lower()
        if sub == "setup":
            await self._cmd_setup(ctx)
        elif sub == "create":
            # !ticket create categoria [razon...]
            if len(args) == 0:
                return await ctx.send("Uso: `!ticket create <categoria> [razón...]` - escribe `!ticket create categorias` para ver las disponibles.")
            cat = args[0].lower()
            if cat == "categorias":
                cats = self.cfg.get("categories", {})
                lines = [f"{info['emoji']} **{k}** — {info.get('desc','')}" for k, info in cats.items()]
                return await ctx.send("Categorías disponibles:\n" + "\n".join(lines))
            reason = " ".join(args[1:]) if len(args) > 1 else None
            if cat not in self.cfg.get("categories", {}):
                return await ctx.send("Categoría no válida. Usa `!ticket create categorias` para ver las disponibles.")
            channel, ticket_obj = await self.create_ticket_channel(ctx.guild, ctx.author, cat, reason)
            await ctx.send(f"Ticket creado: {channel.mention}")
        elif sub == "close":
            await self._cmd_close(ctx, args)
        elif sub == "claim":
            await self._cmd_claim(ctx)
        elif sub == "add":
            await self._cmd_add(ctx, args)
        elif sub == "remove":
            await self._cmd_remove(ctx, args)
        elif sub == "list":
            await self._cmd_list(ctx)
        elif sub == "info":
            await self._cmd_info(ctx)
        elif sub == "rename":
            await self._cmd_rename(ctx, args)
        elif sub == "panel":
            await self._cmd_panel(ctx)
        elif sub == "transcript":
            await self._cmd_transcript(ctx)
        else:
            await ctx.send("Subcomando desconocido. Usa `!ticket` para ver ayuda.")

    async def _cmd_setup(self, ctx: commands.Context):
        # Solo admins
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("Necesitas permisos de administrador para ejecutar esto.")
        # Crear categoría (si no existe) y canal panel
        cfg = self.cfg
        guild = ctx.guild
        category = None
        cat_id = cfg.get("ticket_category_id")
        if cat_id:
            category = guild.get_channel(int(cat_id))
            if category and not isinstance(category, discord.CategoryChannel):
                category = None
        if not category:
            category_name = cfg.get("ticket_category_name", "Lunar Market Tickets")
            category = discord.utils.get(guild.categories, name=category_name)
            if not category:
                category = await guild.create_category(category_name, reason="Setup de tickets Lunar Market")

        # crear canal panel si no existe
        panel_name = cfg.get("panel_channel_name", "🎫-crear-ticket")
        panel_channel = discord.utils.get(guild.text_channels, name=panel_name)
        if not panel_channel:
            panel_channel = await guild.create_text_channel(panel_name, category=category, reason="Canal panel tickets Lunar Market")

        # construir embed bonito con categorías y emojis
        cats = cfg.get("categories", {})
        description_lines = []
        for key, info in cats.items():
            description_lines.append(f"{info.get('emoji','')} **{key}** — {info.get('desc','')}")
        embed = discord.Embed(title="🎟️ Lunar Market — Crear un Ticket", description="\n".join(description_lines), color=0x6A5ACD, timestamp=datetime.utcnow())
        embed.set_footer(text="Reacciona con el emoji correspondiente para crear un ticket en esa categoría.")
        embed.set_thumbnail(url="https://i.imgur.com/rdm3W9t.png")  # placeholder, cámbiala si quieres
        msg = await panel_channel.send(embed=embed)
        # Añadir reacciones (manejar custom emojis y unicode)
        for info in cats.values():
            emo = info.get("emoji", "🛎️")
            try:
                await msg.add_reaction(emo)
            except Exception:
                # intentar con PartialEmoji
                try:
                    partial = discord.PartialEmoji.from_str(emo)
                    await msg.add_reaction(partial)
                except Exception:
                    pass
        cfg["panel_message_id"] = msg.id
        cfg["panel_channel_id"] = panel_channel.id
        save_config(cfg)
        await ctx.send(f"Panel creado en {panel_channel.mention}. Usuarios podrán reaccionar para crear tickets.")

    async def _cmd_claim(self, ctx: commands.Context):
        cfg = self.cfg
        if not is_staff(ctx.author, cfg):
            return await ctx.send("Solo el staff puede reclamar tickets.")
        # buscar ticket por canal
        ticket = self._get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            return await ctx.send("Este canal no parece ser un ticket.")
        if ticket.get("claimed_by"):
            return await ctx.send("Este ticket ya fue reclamado.")
        ticket["claimed_by"] = ctx.author.id
        self.data["tickets"][str(ticket["id"])] = ticket
        self._save()
        await ctx.send(f"✅ {ctx.author.mention} reclamó este ticket.")

    async def _cmd_close(self, ctx: commands.Context, args):
        ticket = self._get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            return await ctx.send("Este canal no parece ser un ticket.")
        # solo staff o owner puede cerrar
        cfg = self.cfg
        if ctx.author.id != ticket["owner_id"] and not is_staff(ctx.author, cfg) and not ctx.author.guild_permissions.administrator:
            return await ctx.send("Solo el creador del ticket, staff o administrador puede cerrarlo.")
        reason = " ".join(args) if args else "Cerrado"
        # marcar cerrado
        ticket["status"] = "closed"
        ticket["closed_at"] = datetime.utcnow().isoformat()
        ticket["close_reason"] = reason
        self.data["tickets"][str(ticket["id"])] = ticket
        self._save()

        # Renombrar canal y establecer permisos de solo lectura para el owner
        try:
            new_name = f"closed-{ctx.channel.name}"
            await ctx.channel.edit(name=new_name)
            owner = ctx.guild.get_member(ticket["owner_id"])
            if owner:
                await ctx.channel.set_permissions(owner, send_messages=False, read_message_history=True, view_channel=True)
            await ctx.send(f"🔒 Ticket cerrado. Razón: {reason}")
        except Exception:
            await ctx.send("Ticket marcado como cerrado (no se pudo renombrar/ajustar permisos).")

        # generar transcript y enviarlo al canal de logs (si está configurado)
        await self._send_transcript_to_logs(ctx.channel, ticket)

    async def _cmd_add(self, ctx: commands.Context, args):
        if not args:
            return await ctx.send("Uso: `!ticket add @usuario`")
        ticket = self._get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            return await ctx.send("Este canal no parece ser un ticket.")
        # solo staff o owner puede agregar
        cfg = self.cfg
        if ctx.author.id != ticket["owner_id"] and not is_staff(ctx.author, cfg) and not ctx.author.guild_permissions.administrator:
            return await ctx.send("Solo el creador del ticket, staff o administrador puede añadir usuarios.")
        member = ctx.message.mentions[0] if ctx.message.mentions else None
        if not member:
            return await ctx.send("Menciona al usuario que quieres añadir.")
        await ctx.channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True)
        await ctx.send(f"➕ {member.mention} fue añadido al ticket.")

    async def _cmd_remove(self, ctx: commands.Context, args):
        if not args:
            return await ctx.send("Uso: `!ticket remove @usuario`")
        ticket = self._get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            return await ctx.send("Este canal no parece ser un ticket.")
        cfg = self.cfg
        if ctx.author.id != ticket["owner_id"] and not is_staff(ctx.author, cfg) and not ctx.author.guild_permissions.administrator:
            return await ctx.send("Solo el creador del ticket, staff o administrador puede remover usuarios.")
        member = ctx.message.mentions[0] if ctx.message.mentions else None
        if not member:
            return await ctx.send("Menciona al usuario que quieres remover.")
        await ctx.channel.set_permissions(member, overwrite=None)
        await ctx.send(f"➖ {member.mention} fue removido del ticket.")

    async def _cmd_list(self, ctx: commands.Context):
        cfg = self.cfg
        if not is_staff(ctx.author, cfg) and not ctx.author.guild_permissions.administrator:
            return await ctx.send("Solo staff o administradores pueden ver la lista de tickets.")
        # listar tickets abiertos en este guild
        open_tickets = []
        for tid, t in self.data.get("tickets", {}).items():
            if t.get("guild_id") == ctx.guild.id and t.get("status") == "open":
                owner = ctx.guild.get_member(t.get("owner_id"))
                ch = ctx.guild.get_channel(t.get("channel_id"))
                open_tickets.append(f"#{t['id']} — {t['category']} — {owner.mention if owner else t['owner_id']} — {ch.mention if ch else 'canal eliminado'}")
        if not open_tickets:
            return await ctx.send("No hay tickets abiertos en este servidor.")
        # mostrar (si es mucha info, se puede paginar; aquí simple)
        await ctx.send("📋 Tickets abiertos:\n" + "\n".join(open_tickets))

    async def _cmd_info(self, ctx: commands.Context):
        ticket = self._get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            return await ctx.send("Este canal no parece ser un ticket.")
        owner = ctx.guild.get_member(ticket.get("owner_id"))
        claimer = ctx.guild.get_member(ticket.get("claimed_by")) if ticket.get("claimed_by") else None
        embed = discord.Embed(title=f"ℹ️ Info Ticket #{ticket['id']}", color=0x00FFAA)
        embed.add_field(name="Categoría", value=ticket.get("category", "N/A"), inline=True)
        embed.add_field(name="Estado", value=ticket.get("status", "N/A"), inline=True)
        embed.add_field(name="Creador", value=owner.mention if owner else str(ticket.get("owner_id")), inline=True)
        embed.add_field(name="Reclamado por", value=claimer.mention if claimer else "Sin reclamar", inline=True)
        embed.add_field(name="Razón", value=ticket.get("reason", "N/A"), inline=False)
        embed.add_field(name="Creado", value=ticket.get("created_at", "N/A"), inline=True)
        if ticket.get("status") == "closed":
            embed.add_field(name="Cerrado", value=ticket.get("closed_at", "N/A"), inline=True)
            embed.add_field(name="Motivo cierre", value=ticket.get("close_reason", "N/A"), inline=False)
        await ctx.send(embed=embed)

    async def _cmd_rename(self, ctx: commands.Context, args):
        if not args:
            return await ctx.send("Uso: `!ticket rename nuevo-nombre`")
        ticket = self._get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            return await ctx.send("Este canal no parece ser un ticket.")
        # solo staff o owner puede renombrar
        cfg = self.cfg
        if ctx.author.id != ticket["owner_id"] and not is_staff(ctx.author, cfg) and not ctx.author.guild_permissions.administrator:
            return await ctx.send("Solo el creador del ticket, staff o administrador puede renombrarlo.")
        new_name = "-".join(args)
        try:
            await ctx.channel.edit(name=new_name)
            await ctx.send(f"✏️ Canal renombrado a `{new_name}`.")
        except Exception as e:
            await ctx.send(f"No pude renombrar el canal: {e}")

    async def _cmd_panel(self, ctx: commands.Context):
        # repostear el panel en el canal especificado por config o en canal actual
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("Necesitas permisos de administrador para crear/actualizar el panel.")
        cfg = self.cfg
        cats = cfg.get("categories", {})
        description_lines = []
        for key, info in cats.items():
            description_lines.append(f"{info.get('emoji','')} **{key}** — {info.get('desc','')}")
        embed = discord.Embed(title="🎟️ Lunar Market — Crear un Ticket", description="\n".join(description_lines), color=0x6A5ACD, timestamp=datetime.utcnow())
        embed.set_footer(text="Reacciona con el emoji correspondiente para crear un ticket en esa categoría.")
        embed.set_thumbnail(url="https://i.imgur.com/rdm3W9t.png")
        target = ctx.channel
        msg = await target.send(embed=embed)
        for info in cats.values():
            emo = info.get("emoji", "🛎️")
            try:
                await msg.add_reaction(emo)
            except Exception:
                try:
                    partial = discord.PartialEmoji.from_str(emo)
                    await msg.add_reaction(partial)
                except Exception:
                    pass
        cfg["panel_message_id"] = msg.id
        cfg["panel_channel_id"] = target.id
        save_config(cfg)
        await ctx.send("Panel creado/actualizado.")

    async def _cmd_transcript(self, ctx: commands.Context):
        ticket = self._get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            return await ctx.send("Este canal no parece ser un ticket.")
        await ctx.send("Generando transcript (esto puede tardar)...")
        await self._send_transcript_to_logs(ctx.channel, ticket, notify_channel=True)

    def _get_ticket_by_channel(self, channel_id):
        for tid, t in self.data.get("tickets", {}).items():
            if t.get("channel_id") == channel_id:
                return t
        return None

    async def _send_transcript_to_logs(self, channel: discord.TextChannel, ticket: dict, notify_channel=False):
        cfg = self.cfg
        log_id = cfg.get("log_channel_id")
        if not log_id:
            if notify_channel:
                await channel.send("No hay canal de logs configurado. Edita config.json añadiendo log_channel_id.")
            return
        guild = channel.guild
        log_channel = guild.get_channel(int(log_id))
        if not log_channel:
            if notify_channel:
                await channel.send("Canal de logs no encontrado en el servidor.")
            return
        # obtener mensajes
        msgs = []
        async for m in channel.history(limit=None, oldest_first=True):
            ts = m.created_at.strftime("%Y-%m-%d %H:%M:%S")
            author = f"{m.author} ({m.author.id})"
            content = m.content or ""
            # incluir attachments
            if m.attachments:
                content += "\n" + " ".join(a.url for a in m.attachments)
            msgs.append(f"[{ts}] {author}: {content}")
        transcript_text = "\n".join(msgs)[:1900000]  # prevenir tamaño excesivo
        filename = f"transcript-ticket-{ticket['id']}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(transcript_text)
        await log_channel.send(f"🗂️ Transcript del ticket #{ticket['id']} ({ticket.get('category')}), creado por <@{ticket.get('owner_id')}>", file=discord.File(filename))
        try:
            os.remove(filename)
        except Exception:
            pass
        if notify_channel:
            await channel.send(f"Transcript enviado a {log_channel.mention}.")

    # Listener para reacciones en el panel
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        # Ignorar reacciones del bot
        if payload.user_id == self.bot.user.id:
            return
        cfg = load_config()
        panel_id = cfg.get("panel_message_id")
        if not panel_id or payload.message_id != panel_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)
        if not member:
            return
        # detectar categoria por emoji (comparar str(payload.emoji))
        emoji_str = str(payload.emoji)
        chosen = None
        for key, info in cfg.get("categories", {}).items():
            if info.get("emoji") == emoji_str:
                chosen = key
                break
        if not chosen:
            # permitir coincidencias por name/id (por si el emoji en config está en formato <:name:id>)
            for key, info in cfg.get("categories", {}).items():
                try:
                    cfg_emo = info.get("emoji", "")
                    if "<:" in cfg_emo and payload.emoji.id and str(payload.emoji.id) in cfg_emo:
                        chosen = key
                        break
                except Exception:
                    pass
        if not chosen:
            return
        # crear ticket
        guild_obj = guild
        channel, ticket_obj = await self.create_ticket_channel(guild_obj, member, chosen, reason=f"Creado desde panel por reacción {emoji_str}")
        # enviar DM al usuario (intentar)
        try:
            await member.send(f"✅ Tu ticket fue creado en **{guild_obj.name}**: {channel.mention}")
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        # No implementado para quitar reacción (no necesario)
        pass


# Registrar cog en el bot
@bot.event
async def on_ready():
    print(f"Conectado como {bot.user} (id: {bot.user.id})")
    ensure_files()
    print("Listo.")

bot.add_cog(Ticket(bot))

# Ejecutar
if __name__ == "__main__":
    ensure_files()
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        print("Error: define la variable de entorno DISCORD_TOKEN con el token del bot.")
        exit(1)
    bot.run(TOKEN)