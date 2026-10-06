(async () => {
  const sleep=ms => new Promise(resolve=>setTimeout(resolve,ms));
  for(let i=0; i<200 && !document.querySelector(".landing"); i++) await sleep(10);
  if(fixture.scene !== "landing" && fixture.scene !== "empty") await resumeSession("fixture-session");
  if(fixture.scene === "completion") {
    currentCentralQuestion=fixture.sessions["fixture-session"].central_question;
    showCelebration(fixture.progress({equilibrium_score:1,closing_pending:true}));
    deliverClosing("You have examined the questions carefully. Your judgment is now stable within this inquiry, while remaining open to future reflection.");
  }
  if(fixture.scene === "mill") {
    document.title="Inquiry Chat — synthetic Quiet Dialogue preview";
    const label=document.createElement("div");
    label.textContent="Synthetic preview · example conversation";
    label.style.cssText="position:fixed;left:18px;bottom:5px;z-index:10000;font:10px/1.4 system-ui;color:#63788a;background:#fcfbf8e8;padding:2px 5px;border-radius:4px;pointer-events:none";
    document.body.appendChild(label);
  }
  if(new URLSearchParams(location.search).get("toolbar") !== "0") {
    const bar=document.createElement("nav");
    bar.setAttribute("aria-label","Fixture previews");
    bar.style.cssText="position:fixed;bottom:6px;left:50%;transform:translateX(-50%);z-index:10001;background:#ffffffed;border:1px solid #ccd0cc;border-radius:20px;padding:6px 12px;display:flex;gap:10px;font:11px system-ui;box-shadow:0 2px 10px #0001";
    bar.innerHTML='<span style="color:#777">Preview fixtures:</span>'+[["mill","Mill example"],["chat","Mixed states"],["landing","Landing"],["long","Long content"],["chat&voice=off","Voice off"],["completion","Completion"]].map(([scene,label])=>`<a style="color:#345674;white-space:nowrap" href="/fixture?scene=${scene}">${label}</a>`).join("")+ '<a style="color:#345674" href="/runner.html">Tests</a>';
    document.body.appendChild(bar);
  }
  fixture.ready=true;
})();
