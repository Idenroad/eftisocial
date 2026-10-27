"""i18n léger — français (source), anglais, espagnol.

Usage template : {{ t("Texte français") }}
Usage Python   : from .i18n import tr ; tr("Texte")
Résolution langue : ?lang= → cookie efti_lang → Accept-Language → fr.
Les clés sont les chaînes françaises ; une clé absente retourne le français.
"""

from flask import request, g

LANGS = ("fr", "en", "es")
_DEFAULT = "fr"

TRANSLATIONS = {
    # ─── Générique / navigation ───
    "Trouver": {"en": "Discover", "es": "Descubrir"},
    "Découverte": {"en": "Explore", "es": "Explorar"},
    "Événements": {"en": "Events", "es": "Eventos"},
    "Profil": {"en": "Profile", "es": "Perfil"},
    "Mes matchs": {"en": "My matches", "es": "Mis matches"},
    "Retour": {"en": "Back", "es": "Volver"},
    "Ajouter sur mon téléphone": {"en": "Add to my phone", "es": "Añadir a mi teléfono"},
    "Compris": {"en": "Got it", "es": "Entendido"},
    "Continuer": {"en": "Continue", "es": "Continuar"},
    "Enregistrer": {"en": "Save", "es": "Guardar"},

    # ─── Accueil / connexion ───
    "Bienvenue": {"en": "Welcome", "es": "Bienvenido"},
    "Entrez le nom de votre résidence pour continuer.": {
        "en": "Enter your residence name to continue.",
        "es": "Escriba el nombre de su residencia para continuar."},
    "Entrez le nom de votre résidence.": {
        "en": "Enter your residence name.",
        "es": "Escriba el nombre de su residencia."},
    "Ex. : Manoir Bleu": {"en": "E.g.: Blue Manor", "es": "Ej.: Residencia Azul"},
    "Accès superadmin": {"en": "Superadmin access", "es": "Acceso superadmin"},
    "Résidence introuvable. Vérifiez le nom auprès de votre intervenant.": {
        "en": "Residence not found. Check the name with your coordinator.",
        "es": "Residencia no encontrada. Verifique el nombre con su coordinador."},
    "Connexion": {"en": "Sign in", "es": "Iniciar sesión"},
    "Entrez votre courriel. Nous vous enverrons un code à 6 chiffres.": {
        "en": "Enter your email. We will send you a 6-digit code.",
        "es": "Escriba su correo. Le enviaremos un código de 6 dígitos."},
    "votre@courriel.ca": {"en": "your@email.com", "es": "su@correo.com"},
    "Recevoir mon code": {"en": "Send my code", "es": "Enviar mi código"},
    "Vous êtes intervenant ?": {"en": "Are you a staff member?", "es": "¿Es usted personal?"},
    "Vous êtes résident ?": {"en": "Are you a resident?", "es": "¿Es usted residente?"},
    "Votre code": {"en": "Your code", "es": "Su código"},
    "Un code a été envoyé à": {"en": "A code was sent to", "es": "Se envió un código a"},
    "si ce compte existe.": {"en": "if this account exists.", "es": "si esta cuenta existe."},
    "Rester connecté sur cet appareil": {
        "en": "Stay signed in on this device",
        "es": "Permanecer conectado en este dispositivo"},
    "Me connecter": {"en": "Sign me in", "es": "Conectarme"},
    "Code invalide ou expiré.": {"en": "Invalid or expired code.", "es": "Código inválido o expirado."},
    "Compte introuvable.": {"en": "Account not found.", "es": "Cuenta no encontrada."},
    "Adresse courriel invalide.": {"en": "Invalid email address.", "es": "Correo inválido."},
    "Trop de demandes. Réessayez plus tard.": {
        "en": "Too many requests. Try again later.",
        "es": "Demasiadas solicitudes. Inténtelo más tarde."},

    # ─── Trouver / matchs ───
    "Chargement…": {"en": "Loading…", "es": "Cargando…"},
    "C'est un match !": {"en": "It's a match!", "es": "¡Es un match!"},
    "Aucun match pour le moment. Continuez à swiper !": {
        "en": "No matches yet. Keep swiping!",
        "es": "Sin matches por ahora. ¡Siga deslizando!"},
    "Personne de nouveau pour le moment.": {
        "en": "No one new for now.",
        "es": "Nadie nuevo por ahora."},
    "Revenez plus tard ou explorez l'onglet Découverte.": {
        "en": "Come back later or browse the Explore tab.",
        "es": "Vuelva más tarde o explore la pestaña Explorar."},
    "Erreur de chargement.": {"en": "Loading error.", "es": "Error de carga."},
    "passion(s) en commun": {"en": "shared interest(s)", "es": "interés(es) en común"},

    # ─── Tchat ───
    "Écrire un message…": {"en": "Write a message…", "es": "Escriba un mensaje…"},
    "Envoyer": {"en": "Send", "es": "Enviar"},
    "Options du match": {"en": "Match options", "es": "Opciones del match"},
    "réapparaîtra dans votre pool": {
        "en": "will reappear in your pool",
        "es": "reaparecerá en su lista"},
    "Supprimer le match": {"en": "Delete the match", "es": "Eliminar el match"},
    "Bloquer": {"en": "Block", "es": "Bloquear"},
    "Signaler un comportement": {"en": "Report a behavior", "es": "Reportar un comportamiento"},
    "Comportement déplacé": {"en": "Inappropriate behavior", "es": "Comportamiento inapropiado"},
    "Spam / sollicitation": {"en": "Spam / solicitation", "es": "Spam / solicitud"},
    "Photo inappropriée": {"en": "Inappropriate photo", "es": "Foto inapropiada"},
    "Autre": {"en": "Other", "es": "Otro"},
    "Détails (optionnel)": {"en": "Details (optional)", "es": "Detalles (opcional)"},
    "Envoyer le signalement": {"en": "Send the report", "es": "Enviar el reporte"},

    # ─── Découverte ───
    "Explorez les passions des membres de votre résidence.": {
        "en": "Explore the interests of your residence members.",
        "es": "Explore las aficiones de los miembros de su residencia."},
    "Chercher une passion…": {"en": "Search an interest…", "es": "Buscar una afición…"},
    "Toutes": {"en": "All", "es": "Todas"},
    "Mes passions": {"en": "My interests", "es": "Mis aficiones"},
    "Aucune passion enregistrée pour l'instant.": {
        "en": "No interests registered yet.",
        "es": "Ninguna afición registrada por ahora."},
    "Personne d'autre pour cette passion.": {
        "en": "No one else for this interest.",
        "es": "Nadie más para esta afición."},
    "en commun": {"en": "in common", "es": "en común"},

    # ─── Membre ───
    "Aimer ♥": {"en": "Like ♥", "es": "Me gusta ♥"},
    "Aimé ♥": {"en": "Liked ♥", "es": "Me gusta ♥"},
    "Réessayer": {"en": "Try again", "es": "Reintentar"},
    "Options": {"en": "Options", "es": "Opciones"},

    # ─── Événements ───
    "Lieu : ": {"en": "Location: ", "es": "Lugar: "},
    "Par": {"en": "By", "es": "Por"},
    "participant(s)": {"en": "participant(s)", "es": "participante(s)"},
    "Je participe": {"en": "I'm in", "es": "Participo"},
    "Je me désinscris": {"en": "Cancel my spot", "es": "Cancelo mi plaza"},
    "Annuler l'événement": {"en": "Cancel the event", "es": "Cancelar el evento"},
    "Organiser un événement": {"en": "Organize an event", "es": "Organizar un evento"},
    "Titre (ex. : Bingo du jeudi)": {
        "en": "Title (e.g.: Thursday bingo)",
        "es": "Título (ej.: bingo del jueves)"},
    "Lieu (ex. : Salle commune)": {
        "en": "Location (e.g.: Common room)",
        "es": "Lugar (ej.: sala común)"},
    "Description": {"en": "Description", "es": "Descripción"},
    "Date et heure": {"en": "Date and time", "es": "Fecha y hora"},
    "Nb max de participants (optionnel)": {
        "en": "Max participants (optional)",
        "es": "Máx. participantes (opcional)"},
    "Publier l'événement": {"en": "Publish the event", "es": "Publicar el evento"},
    "Aucun événement pour l'instant.": {
        "en": "No events for now.", "es": "Sin eventos por ahora."},
    "Titre et date sont requis.": {
        "en": "Title and date are required.",
        "es": "Título y fecha son obligatorios."},
    "L'événement est complet.": {
        "en": "The event is full.", "es": "El evento está lleno."},

    # ─── Profil ───
    "Mon profil": {"en": "My profile", "es": "Mi perfil"},
    "Votre compte est en pause : les autres membres ne vous voient pas.": {
        "en": "Your account is paused: other members cannot see you.",
        "es": "Su cuenta está en pausa: los demás no le ven."},
    "Mes photos": {"en": "My photos", "es": "Mis fotos"},
    "Ajouter une photo": {"en": "Add a photo", "es": "Añadir una foto"},
    "Mes informations": {"en": "My information", "es": "Mi información"},
    "Prénom": {"en": "First name", "es": "Nombre"},
    "Sexe": {"en": "Gender", "es": "Sexo"},
    "Femme": {"en": "Woman", "es": "Mujer"},
    "Homme": {"en": "Man", "es": "Hombre"},
    "À propos de moi": {"en": "About me", "es": "Sobre mí"},
    "Mes passions (max 10, séparées par des virgules)": {
        "en": "My interests (max 10, comma separated)",
        "es": "Mis aficiones (máx. 10, separadas por comas)"},
    "jardinage, bingo, marche": {
        "en": "gardening, bingo, walking",
        "es": "jardinería, bingo, caminatas"},
    "Profil mis à jour.": {"en": "Profile updated.", "es": "Perfil actualizado."},
    "Prénom et sexe sont requis.": {
        "en": "First name and gender are required.",
        "es": "Nombre y sexo son obligatorios."},
    "Membres bloqués": {"en": "Blocked members", "es": "Miembros bloqueados"},
    "Débloquer": {"en": "Unblock", "es": "Desbloquear"},
    "Compte": {"en": "Account", "es": "Cuenta"},
    "Mettre mon compte en pause": {
        "en": "Pause my account", "es": "Pausar mi cuenta"},
    "Réactiver mon compte": {"en": "Reactivate my account", "es": "Reactivar mi cuenta"},
    "Me déconnecter": {"en": "Sign out", "es": "Cerrar sesión"},
    "Supprimer mon compte": {"en": "Delete my account", "es": "Eliminar mi cuenta"},
    "Cette action est définitive : votre profil, vos photos et vos matchs seront supprimés.": {
        "en": "This is permanent: your profile, photos and matches will be deleted.",
        "es": "Esta acción es definitiva: su perfil, fotos y matches serán eliminados."},
    "Je comprends, supprimer mon compte": {
        "en": "I understand, delete my account",
        "es": "Entiendo, eliminar mi cuenta"},
    "Supprimer définitivement": {"en": "Delete permanently", "es": "Eliminar definitivamente"},
    "Page introuvable": {"en": "Page not found", "es": "Página no encontrada"},
    "Retour à l'accueil": {"en": "Back to home", "es": "Volver al inicio"},
    "Une erreur est survenue.": {"en": "Something went wrong.", "es": "Ocurrió un error."},
    "Fichier trop volumineux.": {"en": "File too large.", "es": "Archivo demasiado grande."},
}


def current_lang() -> str:
    """Langue courante (déjà résolue par before_request)."""
    return getattr(g, "lang", _DEFAULT)


def resolve_lang():
    """Détermine la langue : ?lang= > cookie > Accept-Language > fr."""
    lang = request.args.get("lang")
    if lang in LANGS:
        g.lang = lang
        g.set_lang_cookie = True
        return
    lang = request.cookies.get("efti_lang")
    if lang in LANGS:
        g.lang = lang
        return
    best = request.accept_languages.best_match(LANGS)
    g.lang = best or _DEFAULT


def tr(s: str) -> str:
    """Traduit une chaîne française vers la langue courante."""
    lang = current_lang()
    if lang == _DEFAULT:
        return s
    return TRANSLATIONS.get(s, {}).get(lang, s)
