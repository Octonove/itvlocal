"""Ventana principal de ITVLocal: pasar la inspeccion, ver los puntos en vivo
y guardar el certificado PDF."""

from __future__ import annotations

import logging
import os
import threading
from datetime import date, datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from . import APP_NAME, APP_VERSION, theme
from . import checks, report, scoring
from .config import AppConfig, load_config, save_config

logger = logging.getLogger(__name__)

SEMAFORO = {checks.OK: ("●", theme.SUCCESS), checks.LEVE: ("●", "#D97706"),
            checks.GRAVE: ("●", theme.DANGER), checks.MUY_GRAVE: ("●", "#7F1D1D"),
            checks.NO_VERIFICADO: ("○", theme.MUTED)}


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        # Las fuentes en puntos crecen con el DPI pero una geometry en pixeles
        # fisicos no: a 125-150% de escalado la ventana fija se quedaba corta y
        # pack recortaba la botonera inferior. Se escala con el DPI real, con
        # tope en el tamano de pantalla (el -80 deja hueco a la barra de tareas).
        f = self.winfo_fpixels("1i") / 96
        w = min(int(880 * f), self.winfo_screenwidth())
        h = min(int(680 * f), self.winfo_screenheight() - 80)
        self.geometry(f"{w}x{h}")
        self.minsize(min(int(820 * f), w), min(int(620 * f), h))
        theme.apply(self)
        try:
            ico = Path(__file__).resolve().parent.parent / "build" / "icon.ico"
            if ico.is_file():
                self.iconbitmap(str(ico))
        except tk.TclError:
            pass

        self.cfg: AppConfig = load_config()
        self.puntos: list[checks.Punto] = []
        self.veredicto: scoring.Veredicto | None = None
        self._inspeccionando = False
        self._closing = False

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(300, self._first_run_check)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        theme.header(self, APP_NAME, "La ITV de tu ordenador · solo inspecciona, nunca toca nada")
        self.status = theme.status_bar(self, "Pulsa 'Pasar la inspeccion' (tarda 1-3 minutos).")

        top = ttk.Frame(self, padding=(16, 12))
        top.pack(fill="x")
        self.btn_itv = ttk.Button(top, text="🔧  Pasar la inspeccion", style="Primary.TButton",
                                  command=self._start)
        self.btn_itv.pack(side="left")
        meta = ttk.Frame(top)
        meta.pack(side="left", padx=16, fill="x", expand=True)
        ttk.Label(meta, text="Nombre del equipo o negocio (sale en el certificado)",
                  style="Muted.TLabel").pack(anchor="w")
        self.var_equipo = tk.StringVar(value=self.cfg.equipo or os.environ.get("COMPUTERNAME", ""))
        ttk.Entry(meta, textvariable=self.var_equipo, width=36).pack(anchor="w", fill="x")
        ttk.Button(top, text="Configurar IA…", command=self._ai_dialog).pack(side="right")
        ttk.Button(top, text="Carpeta de salida…", command=self._set_output_dir).pack(
            side="right", padx=(0, 6))

        # La botonera va con side="bottom" y ANTES que el body: pack recorta
        # primero al ultimo empaquetado, y si la ventana se queda corta (DPI
        # alto, pantalla pequena) debe encogerse la tabla, nunca desaparecer
        # el boton de guardar el certificado.
        bar = ttk.Frame(self, padding=(16, 10))
        bar.pack(fill="x", side="bottom")
        self.btn_pdf = ttk.Button(bar, text="📄 Guardar certificado PDF", style="Primary.TButton",
                                  command=self._save_pdf, state="disabled")
        self.btn_pdf.pack(side="right")
        self.btn_ia = ttk.Button(bar, text="🤖 Explicar con IA", command=self._explicar_ia,
                                 state="disabled")
        self.btn_ia.pack(side="right", padx=(0, 6))
        ttk.Button(bar, text="Abrir carpeta", command=self._open_folder).pack(side="left")

        body = ttk.Frame(self, padding=(16, 4))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        # resultado (arriba, se rellena al terminar)
        res = ttk.Frame(body)
        res.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.lbl_resultado = ttk.Label(res, text="", font=(theme.FONT, 20, "bold"))
        self.lbl_resultado.pack(side="left")
        self.lbl_proxima = ttk.Label(res, text="", style="Muted.TLabel")
        self.lbl_proxima.pack(side="left", padx=(16, 0), pady=(8, 0))

        # tabla de puntos
        cols = ("estado", "punto", "valor")
        self.tree = ttk.Treeview(body, columns=cols, show="headings", height=13)
        self.tree.heading("estado", text="Estado")
        self.tree.heading("punto", text="Punto de inspeccion")
        self.tree.heading("valor", text="Dato")
        self.tree.column("estado", width=140, anchor="w", stretch=False)
        self.tree.column("punto", width=300, anchor="w")
        self.tree.column("valor", width=280, anchor="w")
        self.tree.grid(row=1, column=0, sticky="nsew")
        for estado, (_s, color) in SEMAFORO.items():
            self.tree.tag_configure(estado, foreground=color)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # detalle del punto seleccionado
        self.txt_detalle = tk.Text(body, height=4, wrap="word", font=(theme.FONT, 10),
                                   bg=theme.CARD, relief="solid", borderwidth=1,
                                   state="disabled")
        self.txt_detalle.grid(row=2, column=0, sticky="ew", pady=(8, 0))

    # ------------------------------------------------------------ inspeccion
    def _start(self) -> None:
        if self._inspeccionando:
            return
        self._inspeccionando = True
        self.puntos = []
        self.veredicto = None
        self.tree.delete(*self.tree.get_children())
        self.lbl_resultado.config(text="")
        self.lbl_proxima.config(text="")
        self.btn_pdf.config(state="disabled")
        self.btn_ia.config(state="disabled")
        self.btn_itv.config(state="disabled", text="Inspeccionando…")
        self._set_status("Inspeccionando… los puntos van apareciendo segun se comprueban.")

        self.txt_detalle.config(state="normal")
        self.txt_detalle.delete("1.0", "end")
        self.txt_detalle.config(state="disabled")

        def on_punto(p: checks.Punto, i: int, total: int):
            if not self._closing:
                try:
                    self.after(0, self._add_punto, p, i, total)
                except (tk.TclError, RuntimeError):
                    pass    # la app se cerro entre el check y el after

        def runner():
            puntos = checks.inspeccionar(on_punto=on_punto)
            if not self._closing:
                try:
                    self.after(0, self._done, puntos)
                except (tk.TclError, RuntimeError):
                    pass
        threading.Thread(target=runner, daemon=True).start()

    def _add_punto(self, p: checks.Punto, i: int, total: int) -> None:
        try:
            self.puntos.append(p)     # el panel de detalle funciona ya en vivo
            simbolo, _ = SEMAFORO[p.estado]
            self.tree.insert("", "end", iid=p.clave, tags=(p.estado,),
                             values=(f"{simbolo} {checks.ETIQUETA[p.estado]}", p.nombre, p.valor))
            self._set_status(f"Inspeccionando… {i}/{total} puntos comprobados.")
        except tk.TclError:
            pass

    def _done(self, puntos: list[checks.Punto]) -> None:
        self._inspeccionando = False
        self.puntos = puntos
        self.veredicto = scoring.calcular(puntos)
        v = self.veredicto
        color = {"FAVORABLE": theme.SUCCESS, "DESFAVORABLE": "#D97706",
                 "NEGATIVA": theme.DANGER}[v.resultado]
        try:
            self.btn_itv.config(state="normal", text="🔧  Pasar la inspeccion")
            self.lbl_resultado.config(text=f"{v.resultado} · {v.nota:g}/10", foreground=color)
            self.lbl_proxima.config(
                text=f"Proxima inspeccion: {v.proxima.strftime('%d/%m/%Y')} · "
                     f"{v.n_muy_graves} muy graves, {v.n_graves} graves, {v.n_leves} leves")
            self.btn_pdf.config(state="normal")
            if scoring.plan_de_accion(puntos):
                self.btn_ia.config(state="normal")
            self._set_status("Inspeccion terminada. Guarda el certificado en PDF.")
        except tk.TclError:
            return
        # recordatorio para el proximo arranque
        self.cfg.equipo = self.var_equipo.get().strip()
        self.cfg.ultima_itv = date.today().isoformat()
        self.cfg.proxima_itv = v.proxima.isoformat()
        save_config(self.cfg)

    def _on_select(self, _e=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        p = next((x for x in self.puntos if x.clave == sel[0]), None)
        if p is None:
            return
        texto = p.detalle + (f"\n\nQue hacer: {p.consejo}" if p.consejo else "")
        self.txt_detalle.config(state="normal")
        self.txt_detalle.delete("1.0", "end")
        self.txt_detalle.insert("1.0", texto)
        self.txt_detalle.config(state="disabled")

    # ------------------------------------------------------------- salida
    def _save_pdf(self) -> None:
        if not self.puntos or self.veredicto is None:
            return
        equipo = self.var_equipo.get().strip()
        safe = "".join(c for c in (equipo or "equipo") if c.isalnum() or c in " -_").strip() or "equipo"
        stamp = datetime.now().strftime("%Y-%m-%d")
        # si ya hay certificado de hoy, se desambigua (_2, _3...): nunca se pisa
        out = report.ruta_libre(Path(self.cfg.output_dir) / f"ITV_{safe}_{stamp}.pdf")
        try:
            report.exportar_certificado(self.puntos, self.veredicto, str(out), equipo=equipo)
        except Exception as exc:  # noqa: BLE001
            logger.exception("export fallo")
            messagebox.showerror(APP_NAME, f"No se pudo guardar el certificado:\n{exc}")
            return
        self._set_status(f"Certificado guardado: {out}")
        if messagebox.askyesno(APP_NAME, f"Certificado guardado en:\n{out}\n\n¿Abrirlo ahora?"):
            try:
                os.startfile(str(out))
            except OSError:
                pass

    def _explicar_ia(self) -> None:
        """Reescribe el plan de accion 'como a tu cunado' con la IA configurada.
        Todo el trabajo (incluida la deteccion de IA, que hace una peticion HTTP)
        corre en un hilo: el hilo de la UI no se bloquea nunca."""
        plan = scoring.plan_de_accion(self.puntos)
        if not plan:
            return
        self.btn_ia.config(state="disabled")
        self._set_status("La IA esta redactando la explicacion…")
        listado = "\n".join(f"- {p.nombre} ({checks.ETIQUETA[p.estado]}): {p.detalle} "
                            f"Consejo: {p.consejo}" for p in plan)

        def runner():
            from octonove_core import llm
            if not llm.available():
                out = None
                aviso = True
            else:
                aviso = False
                out = llm.generate(
                    "Explica este plan de accion de mantenimiento de un PC a una persona sin "
                    "conocimientos, en espanol llano y cercano, en una lista ordenada por "
                    "urgencia, maximo 200 palabras, sin tecnicismos:\n" + listado,
                    system="Eres un tecnico informatico paciente que explica sin asustar.",
                    timeout=90)
            if not self._closing:
                try:
                    self.after(0, self._show_ia, out, aviso)
                except (tk.TclError, RuntimeError):
                    pass
        threading.Thread(target=runner, daemon=True).start()

    def _show_ia(self, texto: str | None, sin_ia: bool = False) -> None:
        if self._inspeccionando:
            return          # hay una inspeccion nueva en marcha: no pisar su estado
        try:
            self.btn_ia.config(state="normal")
        except tk.TclError:
            return
        if sin_ia:
            messagebox.showinfo(APP_NAME, "Configura primero una IA (boton 'Configurar IA…'): "
                                "Ollama gratis en tu PC o una API con tu clave.")
            self._set_status("Sin IA configurada.")
            return
        if not texto:
            self._set_status("La IA no respondio; el plan del certificado sigue disponible.")
            return
        self._set_status("Explicacion lista.")
        win = tk.Toplevel(self)
        theme.center_window(win)
        win.title("Tu plan, explicado")
        win.configure(bg=theme.BG)
        win.transient(self)
        frm = ttk.Frame(win, padding=14)
        frm.pack(fill="both", expand=True)
        txt = tk.Text(frm, width=72, height=18, wrap="word", font=(theme.FONT, 10),
                      bg=theme.WHITE, relief="solid", borderwidth=1)
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", texto.strip())
        txt.config(state="disabled")
        ttk.Button(frm, text="Cerrar", command=win.destroy).pack(anchor="e", pady=(8, 0))

    def _set_output_dir(self) -> None:
        d = filedialog.askdirectory(title="Carpeta donde guardar los certificados",
                                    initialdir=self.cfg.output_dir, parent=self)
        if d:
            self.cfg.output_dir = d
            save_config(self.cfg)
            self._set_status(f"Carpeta de salida: {d}")

    def _open_folder(self) -> None:
        try:
            Path(self.cfg.output_dir).mkdir(parents=True, exist_ok=True)
            os.startfile(self.cfg.output_dir)
        except OSError:
            pass

    def _ai_dialog(self) -> None:
        from octonove_core.ai_dialog import show_ai_dialog
        show_ai_dialog(self, on_saved=lambda: self._set_status("IA configurada."))

    # -------------------------------------------------------------- varios
    def _set_status(self, text: str) -> None:
        try:
            self.status.config(text=text)
        except tk.TclError:
            pass

    def _first_run_check(self) -> None:
        if self._closing:
            return
        if not self.cfg.seen_welcome:
            self.cfg.seen_welcome = True
            save_config(self.cfg)
            messagebox.showinfo(
                APP_NAME, "Bienvenido a ITVLocal.\n\n"
                "1. Pulsa 'Pasar la inspeccion' (1-3 minutos).\n"
                "2. Revisa los puntos: verde bien, ambar leve, rojo grave.\n"
                "3. Guarda el certificado PDF con el plan de accion.\n\n"
                "ITVLocal SOLO inspecciona y documenta: jamas borra, 'limpia' ni cambia "
                "nada de tu equipo. Y nada sale de tu PC.")
            return
        # recordatorio de proxima inspeccion
        if self.cfg.proxima_itv:
            try:
                proxima = date.fromisoformat(self.cfg.proxima_itv)
                if date.today() >= proxima:
                    if messagebox.askyesno(APP_NAME, "Toca pasar la inspeccion periodica "
                                           f"(recomendada para el {proxima.strftime('%d/%m/%Y')}).\n\n"
                                           "¿La pasamos ahora?"):
                        self._start()
            except ValueError:
                pass

    def _on_close(self) -> None:
        self._closing = True
        try:
            equipo = self.var_equipo.get().strip()
            if equipo != self.cfg.equipo:
                self.cfg.equipo = equipo
                save_config(self.cfg)
        except tk.TclError:
            pass
        self.destroy()


def main() -> None:
    from .config import setup_logging
    setup_logging()
    App().mainloop()
