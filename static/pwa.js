(() => {
  if ("serviceWorker" in navigator) window.addEventListener("load",()=>navigator.serviceWorker.register("/service-worker.js"));
  if (window.matchMedia("(display-mode: standalone)").matches) return;
  let promptEvent; const button=document.createElement("button");
  button.type="button"; button.textContent="Install Pocketwise"; button.setAttribute("aria-label","Install Pocketwise on this phone");
  Object.assign(button.style,{position:"fixed",right:"14px",bottom:"calc(78px + env(safe-area-inset-bottom))",zIndex:"9999",display:"none",padding:"11px 15px",border:"1px solid #3bd4a0",borderRadius:"999px",background:"#168a68",color:"#fff",fontWeight:"800",boxShadow:"0 12px 34px rgba(0,0,0,.35)"});
  document.body.appendChild(button);
  window.addEventListener("beforeinstallprompt",event=>{event.preventDefault();promptEvent=event;button.style.display="block";});
  button.addEventListener("click",async()=>{if(!promptEvent)return;promptEvent.prompt();await promptEvent.userChoice;promptEvent=null;button.remove();});
  window.addEventListener("appinstalled",()=>button.remove());
})();