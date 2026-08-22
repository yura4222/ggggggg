"""Consent-based MAX sender desktop interface."""
from __future__ import annotations
import queue, threading, tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from max_safe_sender.campaign import Campaign
from max_safe_sender.sender import ApprovedSender
from .automation import DelayRange, MaxAutomation

APP_HOME = Path.home() / ".max-safe-sender"

class FinderApp(tk.Tk):
    def __init__(self):
        super().__init__(); self.title("MAX Safe Sender"); self.geometry("980x760"); self.minsize(820,650)
        self.commands, self.events = queue.Queue(), queue.Queue(); self.stop_event, self.pause_event = threading.Event(), threading.Event()
        self.snapshots=[]; self.pending_batches=[]; self.batch_template=None
        self.image=tk.StringVar(); self.copies=tk.IntVar(value=1); self.dry=tk.BooleanVar(value=True)
        self.delay_min=tk.DoubleVar(value=.3); self.delay_max=tk.DoubleVar(value=.8); self.status=tk.StringVar(value="Готово")
        self._build(); threading.Thread(target=self._worker,daemon=True).start(); self.after(100,self._poll); self.protocol("WM_DELETE_WINDOW",self._close)

    def _build(self):
        root=ttk.Frame(self,padding=18); root.pack(fill="both",expand=True)
        ttk.Label(root,text="MAX Safe Sender",font=("Segoe UI",22,"bold")).pack(anchor="w")
        ttk.Label(root,text="Сканирование, выбор согласованных получателей и контролируемая отправка").pack(anchor="w",pady=(2,12))
        bar=ttk.Frame(root); bar.pack(fill="x")
        ttk.Button(bar,text="Открыть MAX и войти",command=lambda:self.commands.put(("open",))).pack(side="left")
        ttk.Button(bar,text="Сканировать чаты",command=lambda:self.commands.put(("scan",))).pack(side="left",padx=7)
        ttk.Button(bar,text="СТАРТ",command=self._start).pack(side="left")
        ttk.Button(bar,text="ПАУЗА / ПРОДОЛЖИТЬ",command=self._pause).pack(side="left",padx=7)
        ttk.Button(bar,text="ОСТАНОВИТЬ",command=self.stop_event.set).pack(side="left")
        self.next_button=ttk.Button(bar,text="ПРОДОЛЖИТЬ СЛЕДУЮЩИЙ ПАКЕТ",command=self._confirm_next,state="disabled")
        self.next_button.pack(side="right")
        body=ttk.Panedwindow(root,orient="horizontal"); body.pack(fill="both",expand=True,pady=12)
        chats=ttk.LabelFrame(body,text="Получатели — выберите явно",padding=8); body.add(chats,weight=1)
        self.chat_list=tk.Listbox(chats,selectmode="extended",exportselection=False); self.chat_list.pack(fill="both",expand=True)
        compose=ttk.LabelFrame(body,text="Сообщение",padding=10); body.add(compose,weight=2)
        self.message=tk.Text(compose,height=10,wrap="word"); self.message.pack(fill="both",expand=True)
        image_row=ttk.Frame(compose); image_row.pack(fill="x",pady=8)
        ttk.Entry(image_row,textvariable=self.image).pack(side="left",fill="x",expand=True)
        ttk.Button(image_row,text="Изображение…",command=self._image).pack(side="left",padx=(6,0))
        opts=ttk.Frame(compose); opts.pack(fill="x")
        ttk.Label(opts,text="Копий (1–3):").pack(side="left"); ttk.Spinbox(opts,from_=1,to=3,textvariable=self.copies,width=5).pack(side="left",padx=5)
        ttk.Label(opts,text="Задержка, сек.:").pack(side="left",padx=(15,0)); ttk.Spinbox(opts,from_=0.1,to=60,increment=0.1,textvariable=self.delay_min,width=6).pack(side="left"); ttk.Label(opts,text="—").pack(side="left"); ttk.Spinbox(opts,from_=0.1,to=60,increment=0.1,textvariable=self.delay_max,width=6).pack(side="left")
        ttk.Checkbutton(compose,text="Тестовый режим — не отправлять",variable=self.dry).pack(anchor="w",pady=8)
        self.progress=ttk.Progressbar(root); self.progress.pack(fill="x"); ttk.Label(root,textvariable=self.status).pack(anchor="w",pady=4)
        self.log=tk.Text(root,height=10,state="disabled",font=("Consolas",9)); self.log.pack(fill="both",expand=True)

    def _image(self):
        p=filedialog.askopenfilename(filetypes=[("Изображения","*.png *.jpg *.jpeg *.webp")]);
        if p:self.image.set(p)
    def _pause(self):
        if self.pause_event.is_set(): self.pause_event.clear(); self._log("Продолжение")
        else:self.pause_event.set(); self._log("Пауза после текущего действия")
    def _start(self):
        selected=[self.snapshots[i].name for i in self.chat_list.curselection()]
        if not selected: messagebox.showerror("Нет получателей","Выберите чаты в списке"); return
        if self.delay_min.get() < .1 or self.delay_min.get() > self.delay_max.get():
            messagebox.showerror("Неверная задержка","Минимум должен быть не меньше 0.1 и не больше максимума"); return
        batches=[selected[i:i+20] for i in range(0,len(selected),20)]
        summary=f"Получателей: {len(selected)}\nПакетов по 20: {len(batches)}\nКопий: {self.copies.get()}\nТестовый режим: {'да' if self.dry.get() else 'НЕТ'}\n\nЗапустить первый пакет?"
        if not messagebox.askyesno("Подтверждение кампании",summary):return
        self.stop_event.clear(); self.pause_event.clear()
        self.pending_batches=batches
        self.batch_template=(self.message.get("1.0","end-1c"),self.image.get(),self.copies.get(),self.dry.get(),float(self.delay_min.get()),float(self.delay_max.get()))
        state=APP_HOME/"campaign-state.json"
        if state.exists(): state.unlink()
        self._dispatch_next()

    def _dispatch_next(self):
        if not self.pending_batches:return
        recipients=self.pending_batches.pop(0); text,image,copies,dry,dmin,dmax=self.batch_template
        self.next_button.configure(state="disabled")
        self.commands.put(("send",Campaign(tuple(recipients),text,image,copies,dry),dmin,dmax))

    def _confirm_next(self):
        if not self.pending_batches:return
        # The button itself is the explicit confirmation for exactly one batch;
        # no second modal dialog is necessary.
        self._dispatch_next()

    def _worker(self):
        auto=MaxAutomation(APP_HOME/"profile",APP_HOME/"diagnostics",lambda x:self.events.put(("log",x)))
        sender=ApprovedSender(auto,lambda x:self.events.put(("log",x)))
        while True:
            cmd=self.commands.get()
            try:
                if cmd[0]=="close":auto.close();return
                if cmd[0]=="open":auto.open_for_login(True)
                elif cmd[0]=="scan": self.events.put(("chats",auto.snapshot_all_chats(self.stop_event)))
                elif cmd[0]=="send":
                    sender.run(cmd[1],self.snapshots,APP_HOME/"campaign-state.json",self.stop_event,self.pause_event,DelayRange(cmd[2],cmd[3]),lambda n,t:self.events.put(("progress",n,t)))
                    self.events.put(("batch_done",))
            except Exception as e:self.events.put(("error",str(e)))
    def _poll(self):
        while True:
            try:e=self.events.get_nowait()
            except queue.Empty:break
            if e[0]=="log":self._log(e[1])
            elif e[0]=="error":self._log("Ошибка: "+e[1]);messagebox.showerror("Ошибка",e[1])
            elif e[0]=="chats":
                self.snapshots=e[1];self.chat_list.delete(0,"end")
                for x in self.snapshots:self.chat_list.insert("end",x.name)
                self.status.set(f"Найдено чатов: {len(self.snapshots)}")
            elif e[0]=="progress":self.progress.configure(maximum=max(1,e[2]),value=e[1]);self.status.set(f"Отправка: {e[1]}/{e[2]}")
            elif e[0]=="batch_done":
                if self.pending_batches:
                    self.status.set(f"Пакет завершён. Осталось: {len(self.pending_batches)} — нажмите «Продолжить следующий пакет»")
                    self.next_button.configure(state="normal");self._log("Нужно подтверждение следующего пакета")
                else:self.status.set("Кампания завершена");self._log("Все подтверждённые пакеты завершены")
        self.after(100,self._poll)
    def _log(self,text):
        self.log.configure(state="normal");self.log.insert("end",text+"\n");self.log.see("end");self.log.configure(state="disabled")
    def _close(self):self.stop_event.set();self.commands.put(("close",));self.destroy()

def main(): FinderApp().mainloop()
