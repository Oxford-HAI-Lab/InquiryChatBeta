/* Browser-only API, microphone and audio doubles. Loaded before real app.js. */
(() => {
  const query = new URLSearchParams(location.search);
  const clone = value => JSON.parse(JSON.stringify(value));
  const nodes = [
    {id:"CENTRAL", text:"When should we trust a judgment?", parent:null, engagement_score:.75, display_score:1, resolved:true, next_up:false},
    {id:"A_UNTOUCHED", text:"What would make a belief worth holding?", parent:"CENTRAL", engagement_score:0, display_score:0, resolved:false, next_up:false},
    {id:"B_PARTIAL_LOW", text:"Can a sincere judgment still be mistaken?", parent:"CENTRAL", engagement_score:.25, display_score:.25, resolved:false, next_up:false},
    {id:"C_PARTIAL_HIGH", text:"How does experience change our understanding?", parent:"B_PARTIAL_LOW", engagement_score:.7, display_score:.7, resolved:false, next_up:false},
    {id:"D_NEXT", text:"What would persuade you to think again?", parent:"CENTRAL", engagement_score:0, display_score:0, resolved:false, next_up:true},
    {id:"E_PARTIAL_NEXT", text:"How should we meet a thoughtful disagreement?", parent:"CENTRAL", engagement_score:.5, display_score:.5, resolved:false, next_up:true},
    {id:"F_EXPLICIT_FALSE", text:"Can a high score remain explicitly unresolved?", parent:"CENTRAL", engagement_score:.9, display_score:.9, resolved:false, next_up:false},
    {id:"G_LEGACY", text:"A legacy response without new display fields", parent:"CENTRAL", engagement_score:.9},
  ];
  const conversation = [
    {role:"user", content:"I think we should trust our judgment when it has survived **careful questioning**."},
    {role:"assistant", content:"That gives us a useful place to begin. You are connecting confidence with a willingness to examine it.\n\nWhat might distinguish a belief that has been tested from one that has simply become familiar?"},
  ];
  const primary = {session_id:"fixture-session", shard_dir:"fixture/inquiry.json", shard_name:"The examined judgment", central_question:"When should we trust a judgment?", conversation, equilibrium_score:.56, xp:140, level:3, nodes, frontier:["D_NEXT","E_PARTIAL_NEXT","A_UNTOUCHED"], welcome_message:"Welcome. **What do you think?**", welcome_speech:"Welcome. What do you think?", updated_at:"2026-09-30T10:30:00", turn_count:1};
  const second = {...clone(primary), session_id:"older-session", shard_name:"An earlier inquiry", equilibrium_score:.2, xp:30, level:1};
  const state = window.fixture = {
    scene:query.get("scene") || "landing", voice:query.get("voice") !== "off", requests:[], alerts:[], confirms:[], errors:[], confirmAnswer:true,
    sessions:{"fixture-session":primary,"older-session":second}, nextChat:null, speechInstances:[], deferSpeechStart:false, audioPlays:0, audioPauses:0,
    nodes:clone(nodes), clone, ready:false, nextId:0,
    progress(overrides={}) { return {...clone(primary), eval_summary:"Your view is becoming more robust to further questions.", new_achievements:[], ...overrides}; },
  };
  if (state.scene === "mill") {
    // Synthetic visual fixture; dialogue and central question reproduce the
    // Quiet Dialogue design prompt, never a person's saved conversation.
    primary.shard_name="Mill: The Harm Principle";
    primary.central_question="When, if ever, is society justified in interfering with an individual's liberty?";
    primary.conversation=[
      {role:"user",content:"I think society is only justified in interfering when someone is actually harming another person. What people do to themselves is their own business, even if it is unwise."},
      {role:"assistant",content:"What would count as actually harming someone: only physical injury, or also fraud, severe emotional distress, and creating a substantial risk of injury?"},
    ];
    primary.equilibrium_score=.26; primary.xp=260; primary.level=3;
    primary.nodes=[
      {id:"CENTRAL",text:"When may society interfere?",parent:null,engagement_score:.75,display_score:1,resolved:true,next_up:false},
      {id:"A_HARM",text:"What counts as harm?",parent:"CENTRAL",engagement_score:.36,display_score:.36,resolved:false,next_up:true},
      {id:"B_SELF",text:"Which actions affect only oneself?",parent:"CENTRAL",engagement_score:.2,display_score:.2,resolved:false,next_up:true},
      {id:"C_OWNGOOD",text:"May we act for someone's own good?",parent:"CENTRAL",engagement_score:0,display_score:0,resolved:false,next_up:false},
      {id:"D_SOCIETY",text:"What do we owe society?",parent:"CENTRAL",engagement_score:0,display_score:0,resolved:false,next_up:false},
      {id:"E_CASES",text:"How does this apply in practice?",parent:"CENTRAL",engagement_score:0,display_score:0,resolved:false,next_up:false},
    ];
    primary.frontier=["A_HARM","B_SELF","C_OWNGOOD","D_SOCIETY","E_CASES"];
  }
  if (state.scene === "long") {
    primary.central_question = "How can we preserve a thoughtful and independent judgment when our community, our habits, and our institutions each encourage us to see the world in a different way?";
    primary.nodes = Array.from({length:32}, (_,i) => ({...clone(nodes[i % nodes.length]), id:i === 0 ? "CENTRAL" : `NODE_${String(i).padStart(2,"0")}`, text:`${i+1}. ${nodes[i % nodes.length].text} What changes when we consider other people's circumstances?`}));
    primary.conversation = Array.from({length:10},(_,i) => ({role:i%2 ? "assistant":"user", content:(i%2 ? "**A further question.**\n\n" : "My view is that ") + "A considered judgment can develop when we give ourselves the time to understand a difficult question and the reasons another person might answer it differently. ".repeat(i%2 ? 8:4)}));
  }
  if (state.scene === "empty") state.sessions = {};
  window.alert = message => state.alerts.push(String(message));
  window.confirm = message => { state.confirms.push(String(message)); return state.confirmAnswer; };
  window.addEventListener("error", event => state.errors.push(event.message));
  window.addEventListener("unhandledrejection", event => state.errors.push(String(event.reason)));

  class MockSpeechRecognition {
    constructor() { state.speechInstances.push(this); this.running=false; this.startCalls=0; this.abortCalls=0; }
    start() { this.startCalls++; this.running=true; if (!state.deferSpeechStart && this.onstart) this.onstart(); }
    stop() { this.running=false; if (this.onend) this.onend(); }
    abort() { this.abortCalls++; this.running=false; }
    emit(text, final=true) { const result = [{transcript:text}]; result.isFinal=final; if(this.onresult) this.onresult({resultIndex:0,results:[result]}); }
  }
  window.SpeechRecognition = MockSpeechRecognition;
  window.webkitSpeechRecognition = undefined;
  window.MediaSource = undefined; // Verify deterministic blob playback without real audio.
  window.Audio = class {
    constructor(src) { this.src=src; }
    play() { state.audioPlays++; this.timer=setTimeout(() => this.onended && this.onended(),60); return Promise.resolve(); }
    pause() { state.audioPauses++; clearTimeout(this.timer); if(this.onended) this.onended(); }
  };
  const json = (value,status=200) => new Response(JSON.stringify(value),{status,headers:{"Content-Type":"application/json"}});
  window.fetch = async (url, opts={}) => {
    const path = new URL(typeof url === "string" ? url : url.url,location.href).pathname;
    const method = opts.method || "GET";
    const body = opts.body ? JSON.parse(opts.body) : null;
    state.requests.push({path,method,body});
    if(path === "/api/csrf") return json({token:"fixture-browser-authorization"});
    if(!["GET", "HEAD", "OPTIONS"].includes(method) && new Headers(opts.headers).get("X-Inquiry-CSRF") !== "fixture-browser-authorization") {
      return json({detail:"Fixture request missing browser authorization"},403);
    }
    if(path === "/api/tts/enabled") return json({enabled:state.voice,provider:"openai",note:"Mock voice; no audio or external requests."});
    if(path === "/api/shards") return json([{dir:"fixture/inquiry.json",name:"examined_judgment",title:'The examined judgment <test>',central_question:'When should we trust a "judgment"?',node_count:8},{dir:"fixture/second.json",name:"second",title:"Living with disagreement",central_question:"What do we owe one another?",node_count:14}]);
    if(path === "/api/sessions" && method === "GET") return json(Object.values(state.sessions).map(s => ({...s,id:s.session_id})));
    if(path === "/api/sessions/new") {
      const id = `new-session-${++state.nextId}`;
      state.sessions[id] = {...clone(primary),session_id:id,shard_dir:body.shard_dir,central_question:body.central_question || 'When should we trust a "judgment"?',conversation:[],equilibrium_score:0,xp:0,level:1,nodes:clone(nodes).map(n => ({...n,engagement_score:0,display_score:0,resolved:false}))};
      return json({session_id:id});
    }
    const sessionMatch = path.match(/^\/api\/sessions\/([^/]+)$/);
    if(sessionMatch) {
      if(method === "DELETE") { delete state.sessions[sessionMatch[1]]; return json({ok:true}); }
      return state.sessions[sessionMatch[1]] ? json(state.sessions[sessionMatch[1]]) : json({detail:"Fixture session not found"},404);
    }
    const rewindMatch = path.match(/^\/api\/chat\/([^/]+)\/rewind$/);
    if(rewindMatch) {
      const session=state.sessions[rewindMatch[1]];
      session.conversation=session.conversation.slice(0,body.message_index+1);
      return json({...state.progress({equilibrium_score:.2,xp:30,level:1}),conversation:session.conversation});
    }
    const chatMatch = path.match(/^\/api\/chat\/([^/]+)$/);
    if(chatMatch) {
      const config=state.nextChat || {}; state.nextChat=null;
      if(config.error) return json({detail:config.error},500);
      const session=state.sessions[chatMatch[1]];
      const phases=config.phases || [{phase:"reply",assistant_message:"A thoughtful response, ready before the evaluation."},{phase:"eval",...state.progress({equilibrium_score:.68,xp:165,level:4})}];
      session.conversation.push({role:"user",content:body.message});
      for(const phase of phases) if(phase.phase === "reply" || phase.phase === "closing") session.conversation.push({role:"assistant",content:phase.assistant_message});
      const bytes=new TextEncoder();
      return new Response(new ReadableStream({
        async start(controller) {
          for(const phase of phases) {
            await new Promise(resolve => setTimeout(resolve,config.delay || 30));
            const line=JSON.stringify(phase)+"\n";
            // Split in the middle to exercise the real NDJSON buffering path.
            const at=Math.floor(line.length/2);
            controller.enqueue(bytes.encode(line.slice(0,at)));
            controller.enqueue(bytes.encode(line.slice(at)));
          }
          controller.close();
        }
      }),{headers:{"Content-Type":"application/x-ndjson"}});
    }
    if(path === "/api/tts/emotionalize") return json({tagged_text:body.text,instructions:"Calm and thoughtful"});
    if(path === "/api/tts") return new Response(new Uint8Array([0,1,2]),{headers:{"Content-Type":"audio/mpeg"}});
    state.errors.push(`Unmocked fetch blocked: ${method} ${path}`);
    throw new Error(`Unmocked fetch blocked: ${method} ${path}`);
  };
})();
