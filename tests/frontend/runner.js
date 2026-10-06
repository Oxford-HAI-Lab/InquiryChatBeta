/* Integration checks run as local page code, never as browser automation. */
(async () => {
  const frame=document.getElementById("subject"), results=document.getElementById("results");
  const report=window.regression={passed:0,failed:0,results:[],done:false};
  const sleep=ms => new Promise(resolve=>setTimeout(resolve,ms));
  const assert=(value,message)=>{if(!value) throw new Error(message);};
  const equal=(a,b,label)=>assert(a===b,`${label}: expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`);
  async function until(predicate,message="Timed out",timeout=3500) { const deadline=Date.now()+timeout; while(Date.now()<deadline) {if(predicate()) return; await sleep(10);} throw new Error(message); }
  let w,d,f;
  async function load(scene="chat",voice="on") {
    frame.src=`/fixture?scene=${scene}&voice=${voice}&toolbar=0${location.search.includes("baseline")?"&baseline=1":""}`;
    await new Promise(resolve=>frame.onload=resolve);
    w=frame.contentWindow; d=w.document; f=w.fixture;
    await until(()=>f && f.ready,"Fixture did not become ready");
  }
  const click=selector=>{const el=d.querySelector(selector); assert(el,`Missing ${selector}`); el.click();};
  const text=selector=>d.querySelector(selector)?.textContent.trim();
  const requests=path=>f.requests.filter(r=>r.path===path);
  async function send(message="My considered answer") { d.getElementById("chat-input").value=message; const promise=w.sendMessage(); await promise; await sleep(30); }
  async function check(name,fn) {
    const li=document.createElement("li"); results.appendChild(li);
    try { await fn(); report.passed++; li.className="pass"; li.textContent=`PASS — ${name}`; report.results.push({name,pass:true}); }
    catch(error) {report.failed++;li.className="fail";li.textContent=`FAIL — ${name}: ${error.message}`;report.results.push({name,pass:false,error:error.message});}
    document.getElementById("summary").textContent=`${report.passed} passed · ${report.failed} failed · running`;
  }
  await check("Landing lists escaped shards, saved sessions and Continue",async()=>{
    await load("landing"); equal(d.querySelectorAll(".shard-card").length,2,"shards"); equal(d.querySelectorAll(".session-item").length,2,"sessions"); assert(d.querySelector(".continue-btn"),"Continue missing"); assert(text(".shard-card-name").includes("<test>"),"Shard title not preserved as text"); assert(!d.querySelector(".shard-card-name test"),"Shard markup was injected");
  });
  await check("Shard selection preserves data and optional central override",async()=>{
    click(".shard-card"); equal(d.getElementById("shard-dir").value,"fixture/inquiry.json","selected shard"); assert(d.querySelector(".shard-card.selected"),"Selected state missing"); equal(d.getElementById("central-q").placeholder,'When should we trust a "judgment"?',"quoted question");
    d.getElementById("central-q").value="A different central question?"; click(".landing-btn"); await until(()=>d.querySelector(".chat-area")); equal(requests("/api/sessions/new")[0].body.central_question,"A different central question?","override payload"); equal(text(".chat-question"),"A different central question?","override display");
  });
  await check("Unsaved welcome has no rewind and does not consume saved index",async()=>{
    equal(d.querySelectorAll(".message").length,1,"welcome count"); equal(d.querySelectorAll(".msg-rewind-btn").length,0,"welcome rewind"); w.appendMessage("user","A saved thought",false); assert(d.querySelector(".msg-rewind-btn").getAttribute("onclick").includes("rewindTo(0)"),"Welcome shifted saved indices");
  });
  await check("Default question omits optional override from request",async()=>{
    await load("landing"); click(".shard-card"); click(".landing-btn"); await until(()=>d.querySelector(".chat-area")); assert(!("central_question" in requests("/api/sessions/new")[0].body),"Blank override must be omitted");
  });
  await check("Mixed nodes preserve display-score, explicit resolution and legacy fallback",async()=>{
    await load(); const items=[...d.querySelectorAll(".node-item")]; equal(items.length,8,"node count"); assert(items[0].classList.contains("engaged"),"Raw .75 / display 1 must resolve"); equal(items[0].querySelector(".node-score").textContent,"100%","display score"); assert(items[6].classList.contains("partial") && !items[6].classList.contains("engaged"),"Explicit false resolution overwritten"); assert(items[7].classList.contains("engaged"),"Legacy .9 resolution missing"); equal(text("#engaged-count"),"1","server-resolved count");
  });
  await check("Gold brightness, green resolution and next-up ring remain distinct",async()=>{
    const items=[...d.querySelectorAll(".node-item")], dot=i=>items[i].querySelector(".node-dot"), style=i=>w.getComputedStyle(dot(i)); equal(d.querySelectorAll(".node-item.frontier").length,2,"next-up count"); equal(dot(2).style.opacity,"0.55","low score brightness"); equal(dot(3).style.opacity,"0.82","high score brightness"); equal(dot(5).style.opacity,"0.7","partial next brightness"); assert(style(0).backgroundColor!==style(2).backgroundColor,"Green and gold collapsed"); assert(style(1).backgroundColor!==style(2).backgroundColor,"Neutral and partial collapsed"); equal(style(2).backgroundColor,style(5).backgroundColor,"Next-up must preserve gold partial center"); assert(style(4).animationName!=="none" || w.matchMedia("(prefers-reduced-motion: reduce)").matches,"Next-up pulse missing"); assert(items[3].style.paddingLeft==="20px","Nested indentation missing"); assert(items[2].title.includes("sincere"),"Full question tooltip missing");
  });
  await check("Saved messages retain role, markdown, playback and rewind indices",async()=>{
    equal(d.querySelectorAll(".message.user").length,1,"user count"); equal(d.querySelectorAll(".message.assistant").length,1,"assistant count"); assert(d.querySelector(".message.user strong"),"Markdown emphasis missing"); equal(d.querySelectorAll(".msg-play-btn").length,1,"assistant playback"); const buttons=[...d.querySelectorAll(".msg-rewind-btn")]; assert(buttons[0].getAttribute("onclick").includes("rewindTo(0)")&&buttons[1].getAttribute("onclick").includes("rewindTo(1)"),"Saved indices changed");
  });
  await check("Microphone toggles and transcribes into input",async()=>{
    assert(d.getElementById("mic-btn").classList.contains("active"),"Default microphone inactive"); f.speechInstances.at(-1).emit("Spoken answer"); equal(d.getElementById("chat-input").value,"Spoken answer","transcript"); click("#mic-btn"); assert(!d.getElementById("mic-btn").classList.contains("active"),"Microphone failed to stop"); click("#mic-btn"); assert(d.getElementById("mic-btn").classList.contains("active"),"Microphone failed to start");
  });
  await check("Microphone discloses remote processing before a message is sent",async()=>{
    const mic=d.getElementById("mic-btn"),note=d.getElementById("voice-privacy-note");
    assert(note && note.textContent.includes("before you send a message"),"Unsent-audio disclosure missing");
    equal(mic.getAttribute("aria-describedby"),note.id,"microphone privacy description");
    equal(mic.getAttribute("aria-pressed"),"true","enabled microphone state");
  });
  await check("Off during microphone startup aborts capture and rejects late callbacks",async()=>{
    await load(); click("#mic-btn"); f.deferSpeechStart=true; click("#mic-btn");
    const stale=f.speechInstances.at(-1),input=d.getElementById("chat-input"),mic=d.getElementById("mic-btn"); input.value="Keep this unsent draft";
    equal(mic.getAttribute("aria-pressed"),"true","starting microphone enabled"); click("#mic-btn");
    assert(stale.abortCalls>0 && !stale.running,"Starting recognition was not aborted");
    stale.onstart(); stale.emit("A late transcript"); stale.onend();
    equal(input.value,"Keep this unsent draft","late result changed draft"); equal(stale.startCalls,1,"stale end restarted capture");
    equal(mic.getAttribute("aria-pressed"),"false","Off state"); assert(!mic.classList.contains("active"),"Late start reactivated microphone");
    f.deferSpeechStart=false; click("#mic-btn"); const current=f.speechInstances.at(-1);
    stale.onerror({error:"aborted"}); assert(current.running && mic.classList.contains("active"),"Old error stopped the new instance");
  });
  await check("Send invalidates speech callbacks and Off during reply prevents restart",async()=>{
    await load("chat","off"); const stale=f.speechInstances.at(-1),count=f.speechInstances.length; f.nextChat={delay:120};
    d.getElementById("chat-input").value="An explicitly sent thought"; const pending=w.sendMessage();
    assert(stale.abortCalls>0 && !stale.running,"Send did not abort recognition"); click("#mic-btn");
    stale.emit("Unsent late audio"); stale.onend(); equal(d.getElementById("chat-input").value,"","Late result refilled input");
    await pending; equal(f.speechInstances.length,count,"Reply restarted a microphone switched off by the user");
    assert(!f.speechInstances.some(instance=>instance.running),"Capture remains active after Off");
  });
  await check("Exit aborts speech and late start cannot capture on the landing screen",async()=>{
    await load(); const stale=f.speechInstances.at(-1),count=f.speechInstances.length;
    click(".save-exit-btn"); await until(()=>d.querySelector(".landing")); stale.onstart(); stale.emit("Late after exit"); stale.onend();
    assert(stale.abortCalls>0 && !stale.running,"Recognition remained active after Exit"); equal(f.speechInstances.length,count,"Late callback created recognition");
    assert(!d.getElementById("chat-input"),"Late callback reconstructed chat input");
  });
  await check("Enabled recognition still restarts after ordinary silence",async()=>{
    await load(); const active=f.speechInstances.at(-1),starts=active.startCalls; active.onend();
    equal(active.startCalls,starts+1,"silence restart"); assert(active.running && d.getElementById("mic-btn").classList.contains("active"),"Ordinary listening did not resume");
  });
  await check("Speaker and expressive voice keep separate on/off states",async()=>{
    assert(d.getElementById("speaker-btn").classList.contains("active"),"Default speaker inactive"); assert(d.getElementById("emotion-btn").classList.contains("active"),"Default expressive voice inactive"); click("#speaker-btn"); assert(!d.getElementById("speaker-btn").classList.contains("active"),"Speaker did not toggle"); assert(d.getElementById("emotion-btn").classList.contains("active"),"Speaker changed expressive state"); click("#emotion-btn"); assert(!d.getElementById("emotion-btn").classList.contains("active"),"Expressive state did not toggle");
  });
  await check("Playback uses per-message text and restores button",async()=>{
    const before=f.audioPlays; click(".msg-play-btn"); await until(()=>f.audioPlays>before,"Mock audio did not play"); await until(()=>!d.querySelector(".msg-play-btn.playing"),"Playback button stuck"); assert(requests("/api/tts").length>0,"TTS request missing");
  });
  await check("Shift+Enter does not send; Enter sends exactly once at normal detail",async()=>{
    const input=d.getElementById("chat-input"); input.value="Keyboard answer"; const before=requests("/api/chat/fixture-session").length;
    input.dispatchEvent(new w.KeyboardEvent("keydown",{key:"Enter",shiftKey:true,bubbles:true,cancelable:true})); await sleep(20); equal(requests("/api/chat/fixture-session").length,before,"Shift+Enter send count");
    input.dispatchEvent(new w.KeyboardEvent("keydown",{key:"Enter",bubbles:true,cancelable:true})); await until(()=>!d.getElementById("send-btn").disabled); equal(requests("/api/chat/fixture-session").length,before+1,"Enter send count"); equal(requests("/api/chat/fixture-session").at(-1).body.detail_level,1,"Enter detail level");
  });
  await check("Reply arrives before evaluation; pending send disables input action",async()=>{
    f.nextChat={delay:100}; d.getElementById("chat-input").value="A streamed answer"; const pending=w.sendMessage(); assert(d.getElementById("send-btn").disabled,"Send not disabled"); assert(d.getElementById("thinking-msg"),"Thinking indicator missing"); await until(()=>[...d.querySelectorAll(".message.assistant")].at(-1)?.textContent.includes("thoughtful response")); assert(d.getElementById("send-btn").disabled,"Stream unlocked before evaluation"); await pending; assert(!d.getElementById("send-btn").disabled,"Send not re-enabled"); equal(text("#eq-pct"),"68%","updated equilibrium"); equal(text("#level-value"),"4","updated level"); equal(text("#save-indicator"),"saved!","save feedback"); await sleep(1050); equal(text("#xp-value"),"165","animated XP"); equal(text("#eq-big"),"68%","animated equilibrium");
  });
  await check("Quick mouse press sends once; long hold raises detail to four",async()=>{
    let before=requests("/api/chat/fixture-session").length; const btn=d.getElementById("send-btn"); d.getElementById("chat-input").value="Quick press";
    btn.dispatchEvent(new w.MouseEvent("mousedown",{bubbles:true,cancelable:true})); btn.dispatchEvent(new w.MouseEvent("mouseup",{bubbles:true,cancelable:true})); await until(()=>!btn.disabled); equal(requests("/api/chat/fixture-session").length,before+1,"Quick press count"); equal(requests("/api/chat/fixture-session").at(-1).body.detail_level,1,"Quick detail");
    const realNow=w.Date.now; let now=realNow(); w.Date.now=()=>now;
    try {d.getElementById("chat-input").value="Detailed response"; btn.dispatchEvent(new w.MouseEvent("mousedown",{bubbles:true,cancelable:true})); now+=2100; await sleep(45); btn.dispatchEvent(new w.MouseEvent("mouseup",{bubbles:true,cancelable:true}));} finally {w.Date.now=realNow;}
    await until(()=>!btn.disabled); equal(requests("/api/chat/fixture-session").at(-1).body.detail_level,4,"Hold detail");
  });
  await check("Cancelled hold sends nothing; touch press follows send handler",async()=>{
    const btn=d.getElementById("send-btn"), before=requests("/api/chat/fixture-session").length; d.getElementById("chat-input").value="Touch answer"; btn.dispatchEvent(new w.MouseEvent("mousedown",{bubbles:true,cancelable:true})); btn.dispatchEvent(new w.MouseEvent("mouseleave",{bubbles:true})); btn.dispatchEvent(new w.MouseEvent("mouseup",{bubbles:true,cancelable:true})); equal(requests("/api/chat/fixture-session").length,before,"Cancelled send");
    btn.dispatchEvent(new w.Event("touchstart",{bubbles:true,cancelable:true})); btn.dispatchEvent(new w.Event("touchend",{bubbles:true,cancelable:true})); await until(()=>!btn.disabled); equal(requests("/api/chat/fixture-session").length,before+1,"Touch send");
  });
  await check("HTTP error and empty reply recover controls with visible feedback",async()=>{
    f.nextChat={error:"Fixture service unavailable"}; await send(); assert(text("#messages").includes("Fixture service unavailable"),"Server error not displayed"); assert(!d.getElementById("send-btn").disabled,"Send remained disabled on error"); assert(!d.getElementById("thinking-msg"),"Thinking persisted on error");
    f.nextChat={phases:[]}; await send(); assert(text("#messages").includes("empty response"),"Empty stream error missing");
  });
  await check("Rewind cancel is inert; confirmed rewind posts selected saved index",async()=>{
    f.confirmAnswer=false; const before=requests("/api/chat/fixture-session/rewind").length; await w.rewindTo(0); equal(requests("/api/chat/fixture-session/rewind").length,before,"Cancelled rewind"); f.confirmAnswer=true; await w.rewindTo(0); equal(requests("/api/chat/fixture-session/rewind").at(-1).body.message_index,0,"rewind index"); equal(d.querySelectorAll("#messages .message").length,1,"truncated conversation");
  });
  await check("Continue auto-enables microphone, speaker and expressive voice",async()=>{
    await load("landing"); click(".continue-btn"); await until(()=>d.querySelector(".chat-area")); assert(d.getElementById("speaker-btn").classList.contains("active"),"Continue speaker"); assert(d.getElementById("emotion-btn").classList.contains("active"),"Continue expression"); assert(d.getElementById("mic-btn").classList.contains("active"),"Continue microphone");
  });
  await check("Exit stops voice and ordinary resume respects toggled voice preferences",async()=>{
    click("#speaker-btn"); click("#emotion-btn"); click("#mic-btn"); click(".save-exit-btn"); await until(()=>d.querySelector(".landing")); assert(!d.body.classList.contains("chat-active"),"Chat body class remained"); assert(!f.speechInstances.some(instance=>instance.running),"Recognition remained active"); click(".session-info"); await until(()=>d.querySelector(".chat-area")); assert(!d.getElementById("speaker-btn").classList.contains("active"),"Resume reset speaker preference"); assert(!d.getElementById("emotion-btn").classList.contains("active"),"Resume reset expressive preference"); assert(!d.getElementById("mic-btn").classList.contains("active"),"Resume reset microphone preference");
  });
  await check("Delete confirmation preserves or removes only chosen mock session",async()=>{
    await load("landing"); f.confirmAnswer=false; click(".session-delete-btn"); await sleep(20); equal(Object.keys(f.sessions).length,2,"cancelled delete"); f.confirmAnswer=true; click(".session-delete-btn"); await until(()=>d.querySelectorAll(".session-item").length===1); equal(Object.keys(f.sessions).length,1,"confirmed delete"); assert(f.sessions["older-session"],"Wrong session removed");
  });
  await check("Unavailable voice stays visibly unavailable and omits message playback",async()=>{
    await load("chat","off"); equal(d.querySelectorAll(".msg-play-btn").length,0,"Disabled voice playback controls"); equal(d.getElementById("speaker-btn").style.opacity,"0.3","Unavailable speaker opacity"); click("#speaker-btn"); click("#emotion-btn"); equal(f.alerts.length,2,"Voice unavailable feedback"); assert(!d.getElementById("speaker-btn").classList.contains("active"),"Unavailable speaker activated");
  });
  await check("Achievement feedback renders its name and explanation",async()=>{
    w.showAchievement({name:"Thoughtful Explorer",desc:"Three questions considered."}); equal(text(".ach-title"),"Thoughtful Explorer","achievement title"); equal(text(".ach-desc"),"Three questions considered.","achievement description");
  });
  await check("Completion preserves pending/ready reflection and exactly-once append",async()=>{
    w.showCelebration(f.progress({equilibrium_score:1,closing_pending:true})); assert(d.querySelector('[role="dialog"]'),"Completion dialog missing"); assert(text("#celebration-status").includes("Preparing"),"Pending status missing"); const before=d.querySelectorAll(".message").length; w.deliverClosing("A final reflection."); equal(text("#celebration-close"),"Read your closing reflections","ready button"); equal(d.querySelectorAll(".message").length,before,"Closing appeared behind overlay"); click("#celebration-close"); await until(()=>text("#messages").includes("A final reflection.")); equal(d.querySelectorAll(".message").length,before+1,"closing append count"); assert(!d.getElementById("celebration-overlay"),"Completion not dismissed");
  });
  await check("Dismiss pending completion waits, then receives closing; missing closing recovers",async()=>{
    w.showCelebration(f.progress({closing_pending:true})); w.closeCelebration(); assert(d.getElementById("thinking-msg"),"Pending closing indicator missing"); w.deliverClosing("A later reflection."); await until(()=>!d.getElementById("thinking-msg")); assert(text("#messages").includes("A later reflection."),"Late closing missing"); w.showCelebration(f.progress({closing_pending:true})); w.closeCelebration(); w.deliverClosing(null); assert(!d.getElementById("thinking-msg"),"Missing closing left thinking state");
  });
  await check("Streamed completion reaches 100%, offers closing and renders final reflection",async()=>{
    await load("chat","off"); f.nextChat={phases:[{phase:"reply",assistant_message:"Your last response."},{phase:"eval",...f.progress({equilibrium_score:1,closing_pending:true,new_achievements:[{name:"Equilibrium",desc:"Every question resolved."}]})},{phase:"closing",assistant_message:"Your streamed closing reflection."}]}; await send(); equal(text("#eq-pct"),"100%","completion progress"); assert(d.getElementById("celebration-overlay"),"Stream failed to celebrate"); click("#celebration-close"); await until(()=>text("#messages").includes("Your streamed closing reflection."));
  });
  await check("Empty saved-session state still allows selecting a shard",async()=>{
    await load("empty"); assert(!d.querySelector(".continue-btn"),"Continue shown without sessions"); equal(d.querySelectorAll(".session-item").length,0,"empty sessions"); click(".shard-card"); assert(d.querySelector(".shard-card.selected"),"Empty state selection failed");
  });
  await check("Desktop layout keeps composer, controls and map accessible without horizontal overflow",async()=>{
    await load("long","off"); assert(d.documentElement.scrollWidth<=d.documentElement.clientWidth+2,"Horizontal page overflow"); for(const id of ["chat-input","send-btn","mic-btn","speaker-btn","emotion-btn","node-map"]) {const element=d.getElementById(id),box=element.getBoundingClientRect();assert(box.width>0&&box.height>0,`${id} is hidden`);} const box=d.getElementById("chat-input").getBoundingClientRect(); assert(box.bottom<=w.innerHeight+1,"Composer falls below viewport"); equal(f.errors.length,0,"uncaught fixture errors");
  });
  for(const [width,height] of [[390,844],[768,1024],[1440,900]]) {
    await check(`${width}×${height}: long title and conversation retain a visible, usable composer`,async()=>{
      frame.style.width=`${width}px`; frame.style.height=`${height}px`; frame.style.maxWidth="none";
      await load("long","on"); w.scrollTo({top:0,left:0,behavior:"instant"}); await sleep(50);
      equal(w.innerWidth,width,"fixture viewport width"); equal(w.innerHeight,height,"fixture viewport height");
      assert(d.documentElement.scrollWidth<=d.documentElement.clientWidth+2,"Horizontal document overflow");
      assert(!d.querySelector(".app-header nav, .workspace-nav"),"Header must not contain conversation/map navigation");
      if(width<=900) assert(Math.abs(d.querySelector(".app-header").getBoundingClientRect().height-62)<=1,"Mobile header must remain a single 62px row");
      const header=d.querySelector(".chat-header"), messages=d.getElementById("messages"), input=d.getElementById("chat-input");
      equal(text(".chat-question"),f.sessions["fixture-session"].central_question,"Long title truncated in DOM");
      assert(header.scrollWidth<=header.clientWidth+2,"Long question overflows horizontally");
      if(header.scrollHeight>header.clientHeight+2) {header.scrollTop=header.scrollHeight; assert(header.scrollTop>0,"Clipped long title cannot scroll"); header.scrollTop=0;}
      assert(messages.clientHeight>=100,"Long title leaves no usable conversation area");
      assert(messages.scrollHeight>messages.clientHeight,"Long conversation is not independently scrollable");
      messages.scrollTop=messages.scrollHeight; await sleep(40); assert(messages.scrollTop>0,"Conversation failed to scroll");
      for(const id of ["chat-input","send-btn","mic-btn","speaker-btn","emotion-btn"]) {
        const element=d.getElementById(id),box=element.getBoundingClientRect(),style=w.getComputedStyle(element);
        assert(box.width>0&&box.height>0&&style.display!=="none"&&style.visibility!=="hidden",`${id} is hidden`);
        assert(box.left>=-1&&box.right<=width+1&&box.top>=-1&&box.bottom<=height+1,`${id} outside initial viewport: ${Math.round(box.left)},${Math.round(box.top)}–${Math.round(box.right)},${Math.round(box.bottom)}`);
        const hit=d.elementFromPoint(box.left+box.width/2,box.top+box.height/2);
        assert(hit&&(element===hit||element.contains(hit)),`${id} is covered by another element`);
      }
      input.value="An unsent thought preserved while exploring the map.";
    });
    await check(`${width}×${height}: every long-map node is reachable by scrolling without losing draft or messages`,async()=>{
      const input=d.getElementById("chat-input"),messages=d.getElementById("messages"),sidebar=d.querySelector(".sidebar"),map=d.getElementById("node-map");
      const originalInput=input,originalMessages=messages,draft=input.value,originalCount=messages.children.length;
      equal(map.querySelectorAll(".node-item").length,32,"Long map question count");
      const last=map.querySelector(".node-item:last-child");
      if(width<=900) {
        assert(sidebar.getBoundingClientRect().top>=height-2,"Mobile map should follow conversation");
        assert(d.scrollingElement.scrollHeight>height,"Mobile page cannot reach map");
        const heading=d.querySelector(".sidebar-header h2")||sidebar,headerHeight=d.querySelector(".app-header").getBoundingClientRect().height;
        w.scrollTo({top:w.scrollY+heading.getBoundingClientRect().top-headerHeight-16,behavior:"instant"}); await sleep(60);
        assert(w.scrollY>0,"Ordinary page scrolling did not reach the map"); equal(w.location.hash,"","Scrolling the map must not change the URL fragment");
        const mapTop=sidebar.getBoundingClientRect().top,headingBox=heading.getBoundingClientRect(),headerBottom=d.querySelector(".app-header").getBoundingClientRect().bottom;
        assert(headingBox.top>=headerBottom-2&&headingBox.bottom<height,`Map heading is hidden under sticky header (mapTop=${mapTop.toFixed(1)}, headingTop=${headingBox.top.toFixed(1)}, sidebarHeight=${sidebar.getBoundingClientRect().height.toFixed(1)}, headerBottom=${headerBottom.toFixed(1)}, scrollY=${w.scrollY}, viewport=${w.innerWidth}×${w.innerHeight}, documentClientHeight=${d.documentElement.clientHeight}, mapOffsetTop=${sidebar.offsetTop}, scrollMarginTop=${w.getComputedStyle(sidebar).scrollMarginTop})`);
        w.scrollTo({top:w.scrollY+last.getBoundingClientRect().top-(height-last.getBoundingClientRect().height)/2,behavior:"instant"}); await sleep(30);
        const box=last.getBoundingClientRect(); assert(box.top>=headerBottom-2&&box.bottom<=height+2,"Last map question is unreachable");
        w.scrollTo({top:0,behavior:"instant"}); await sleep(60);
        assert(input.getBoundingClientRect().bottom<=height+2,"Scrolling back did not return to composer");
        const titleRegion=d.querySelector(".chat-header").getBoundingClientRect(); assert(titleRegion.top>=headerBottom-2,`Conversation title region is hidden under sticky header (top=${titleRegion.top.toFixed(1)}, headerBottom=${headerBottom.toFixed(1)}, scrollY=${w.scrollY})`);
      } else {
        const scroller=d.querySelector(".node-map-section"),stats=d.querySelector(".stats-row"),initialStats=stats.getBoundingClientRect();
        assert(scroller.scrollHeight>scroller.clientHeight,"Long map should scroll independently on desktop");
        assert(initialStats.top>=sidebar.getBoundingClientRect().top-2&&initialStats.bottom<=height+2,"Desktop metrics footer is not initially visible");
        scroller.scrollTop=scroller.scrollHeight; await sleep(30); assert(scroller.scrollTop>0,"Map scrolling failed");
        const box=last.getBoundingClientRect(),rail=scroller.getBoundingClientRect(); assert(box.top>=rail.top-2&&box.bottom<=rail.bottom+2,"Last map question is unreachable");
        const finalStats=stats.getBoundingClientRect(); assert(Math.abs(finalStats.top-initialStats.top)<=1&&finalStats.bottom<=height+2,"Scrolling the map displaced the persistent metrics footer");
        for(const id of ["xp-value","level-value","engaged-count"]) {const metric=d.getElementById(id),metricBox=metric.getBoundingClientRect();assert(metricBox.top>=0&&metricBox.bottom<=height+2,`${id} is outside viewport after map scrolling`);}
        assert(input.getBoundingClientRect().bottom<=height+2,"Map scroll displaced composer");
        scroller.scrollTop=0;
      }
      equal(d.getElementById("chat-input"),originalInput,"Composer DOM replaced"); equal(d.getElementById("messages"),originalMessages,"Conversation DOM replaced"); equal(input.value,draft,"Unsent draft changed"); equal(messages.children.length,originalCount,"Message count changed"); equal(f.errors.length,0,"uncaught fixture errors");
    });
  }
  await check("390×400: short viewport keeps long title, messages, composer and map in distinct reachable regions",async()=>{
    frame.style.width="390px"; frame.style.height="400px";
    await load("long","on"); w.scrollTo({top:0,left:0,behavior:"instant"}); await sleep(60);
    const sidebar=d.querySelector(".sidebar"),conversation=d.querySelector(".chat-area"),composer=d.querySelector(".chat-input-area"),messages=d.getElementById("messages");
    const mapBox=sidebar.getBoundingClientRect(),chatBox=conversation.getBoundingClientRect(),composerBox=composer.getBoundingClientRect(),messageBox=messages.getBoundingClientRect();
    const positions=`mapTop=${mapBox.top.toFixed(1)}, chatBottom=${chatBox.bottom.toFixed(1)}, composer=${composerBox.top.toFixed(1)}–${composerBox.bottom.toFixed(1)}, messages=${messageBox.top.toFixed(1)}–${messageBox.bottom.toFixed(1)}`;
    assert(d.documentElement.scrollWidth<=d.documentElement.clientWidth+2,"Short viewport has horizontal overflow");
    assert(messages.clientHeight>=64,`Short viewport loses conversation reading area (${positions})`);
    assert(messageBox.bottom<=composerBox.top+2,`Composer overlaps messages (${positions})`);
    assert(mapBox.top>=composerBox.bottom-2&&mapBox.top>=chatBox.bottom-2,`Map overlaps conversation or composer (${positions})`);
    const input=d.getElementById("chat-input"),send=d.getElementById("send-btn");
    input.scrollIntoView({block:"center",behavior:"instant"}); await sleep(30);
    for(const element of [input,send]) {const box=element.getBoundingClientRect(); assert(box.top>=0&&box.bottom<=400+2,`${element.id} cannot be reached by scrolling (top=${box.top.toFixed(1)}, bottom=${box.bottom.toFixed(1)})`);const hit=d.elementFromPoint(box.left+box.width/2,box.top+box.height/2); assert(hit&&(hit===element||element.contains(hit)),`${element.id} is covered at short height`);}
    equal(f.errors.length,0,"uncaught fixture errors");
  });
  await check("Scrolling to the mobile map → Exit → Resume resets the reading position",async()=>{
    frame.style.width="390px"; frame.style.height="844px"; await load("chat","on");
    assert(!d.querySelector(".app-header nav, .workspace-nav"),"Header navigation unexpectedly present");
    const mapHeading=d.querySelector(".sidebar-header h2"),headerHeight=d.querySelector(".app-header").getBoundingClientRect().height;
    w.scrollTo({top:w.scrollY+mapHeading.getBoundingClientRect().top-headerHeight-16,behavior:"instant"}); await sleep(50);
    equal(w.location.hash,"","Map scrolling changed the fragment"); assert(w.scrollY>0,"Ordinary scrolling did not move into map");
    click(".save-exit-btn"); await until(()=>d.querySelector(".landing")); await sleep(30);
    equal(w.location.hash,"","Landing unexpectedly has a workspace fragment"); equal(w.scrollY,0,"Landing scroll position");
    click(".session-info"); await until(()=>d.querySelector(".chat-area")); await sleep(60);
    equal(w.location.hash,"","Resumed conversation unexpectedly has a map fragment"); equal(w.scrollY,0,"Resumed reading position");
    const header=d.querySelector(".app-header").getBoundingClientRect(),title=d.querySelector(".chat-header").getBoundingClientRect(),input=d.getElementById("chat-input").getBoundingClientRect();
    assert(title.top>=header.bottom-2,"Resumed question hidden under header"); assert(input.bottom<=844+2,"Resumed composer not visible"); equal(f.errors.length,0,"uncaught fixture errors");
  });
  report.done=true;
  document.getElementById("summary").textContent=`${report.passed} passed · ${report.failed} failed · complete`;
  document.getElementById("summary").className=report.failed?"fail":"pass";
})();
