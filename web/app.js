"use strict";

const $ = id => document.getElementById(id);
const VIEW_ZH = {photo:"原图视角",front:"正面",back:"背面","3q4_left":"左前 3/4","3q4_right":"右前 3/4",side:"右侧",side_left:"左侧",top:"俯视",bottom:"仰视",detail_keypad:"按键特写",detail_window:"透明件特写"};
const VIEW_EN = {photo:"same view as input image",front:"front view",back:"rear view","3q4_left":"left three-quarter view","3q4_right":"right three-quarter view",side:"right side view",side_left:"left side view",top:"top-down view",bottom:"bottom-up view",detail_keypad:"keypad detail view",detail_window:"transparent window detail view"};
// 6 视图 = 正交六面。角度与 scripts/blender_pass.py 的 VIEW_ANGLES 一一对应，
// 所以「3D 里看的角度」和「结构图/出图拿到的角度」是同一个。
const SIX_VIEWS = ["front","back","side","side_left","top","bottom"];
// 与 scripts/blender_pass.py 的 VIEW_ANGLES 一一对应（同一机位 = 同一角度），
// 所以「3D 里转到的角度」和「出结构图/出图拿到的角度」是同一件事。
const VIEW_ANGLES_3D = {
  front:      [0,     8],
  back:       [180,   8],
  "3q4_left": [-45,  15],
  "3q4_right":[45,   15],
  side:       [90,    8],
  side_left:  [-90,   8],
  top:        [0,    80],
  bottom:     [0,   -25],
  isometric:  [-45,  35]
};
const ALL_VIEWS = ["front","back","side","side_left","top","bottom","3q4_left","3q4_right","detail_keypad","detail_window"];
// 渲染质量档。★ 注意：默认底模是 Lightning 蒸馏模型，步数超 ~20 收益递减、
// 甚至可能过饱和；**提高分辨率对精度的收益通常大于堆步数**。
const QUALITY = {
  draft:    {steps:8,  cfg:2.0},
  standard: {steps:12, cfg:3.0},
  fine:     {steps:20, cfg:3.5},
  max:      {steps:32, cfg:4.0}
};
const STYLE = {
  studio:{label:"浅灰影棚",background:"gradient_gray",text:"clean light-gray gradient studio background"},
  white:{label:"纯白主图",background:"pure_white",text:"seamless pure-white e-commerce background"},
  dark:{label:"深色质感",background:"charcoal_gradient",text:"deep charcoal studio background with refined contrast"}
};
const MATERIAL = {
  matte_plastic:"fine sandblasted matte plastic",
  glossy_plastic:"high-gloss injection molded plastic with crisp specular highlights",
  soft_touch:"soft-touch coated plastic",
  brushed_aluminum:"anodized brushed aluminum",
  sandblasted_metal:"sandblasted anodized metal with even matte metallic grain",
  gunmetal:"dark gunmetal grey with satin metallic sheen",
  polished_metal:"polished stainless steel",
  chrome:"mirror chrome with high reflectivity",
  carbon_fiber:"carbon fiber weave under a clear gloss coat",
  rubber:"matte black rubber with fine pebbled texture",
  leather:"fine-grain leather with subtle natural sheen",
  wood:"natural wood grain with satin varnish"
};
const LIGHT = {
  soft:"large softbox studio lighting, soft contact shadows",
  top:"diffused overhead studio lighting",
  dramatic:"dramatic side and rim lighting with visible edge separation",
  natural:"soft natural window light from the side"
};
const NEGATIVE = "blurry, low quality, warped geometry, extra parts, distorted product shape, inaccurate markings, invented text, fake logo, cluttered background, cartoon, illustration";
// 白模/灰模截图专用负面词：抑制「保持灰色未上材质」这一最常见失败模式（2026-09-27 新增）
const NEGATIVE_CLAY = ", white unpainted plastic, bare grey model, clay render, untextured surface, flat unlit shading, raw 3D viewport screenshot, no material";

const ACCEPT_PASS = new Set(["png","jpg","jpeg","webp","bmp"]);
const ACCEPT_MODEL = new Set(["blend","glb","gltf","obj","stl","fbx","stp","step","3dm"]);
const STANDARD_VIEWS = ["front","3q4_left","3q4_right","side"];
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

let state = {assets:{items:[],models:[]},tasks:[],comfy:{online:false},ui:{blender:false},passJob:null,sku:"",sourceType:"model",modelCount:"4",imageCount:"1",sourceRelLoaded:"",sourceSize:null,sourceProbe:null,style:"studio",preview:"clay",running:false,runCount:0,selectedTask:null,ref:{rel:"",palette:[],strength:"L2_material"}};
let lastFocus = null;

function announce(message){$("statusMessage").textContent=message;}
function getMode(){return state.sourceType==="image"?"image":document.querySelector('input[name="mode"]:checked').value;}
function selectedItem(){return state.assets.items.find(item=>item.sku===state.sku)||null;}
function selectedView(){return state.sourceType==="image"?"photo":$("viewSelect").value;}
function selectedViews(){
  const box=$("viewChecks");
  if(!box)return [selectedView()];
  const picked=[...box.querySelectorAll('input[type="checkbox"]')].filter(el=>el.checked).map(el=>el.dataset.view);
  // 一个都没勾时退回「预览视角」，避免计算出 0 张让人以为坏了
  return picked.length?picked:[selectedView()];
}
function renderViews(){return state.sourceType==="image"?["photo"]:selectedViews();}
function sourceSize(){
  const size=state.sourceSize;if(!size)return null;
  const scale=Math.min(1,1024/Math.max(size.width,size.height));
  const width=Math.floor(size.width*scale/8)*8,height=Math.floor(size.height*scale/8)*8;
  return Math.min(width,height)>=256?{width,height}:null;
}
// 判断上传的「产品图片」是不是白模/灰模截图 —— 用低饱和 + 高亮度 + 大面积近黑背景三个特征。
// 白模截图当成品照片处理会得到"基本没渲染"的结果（2026-09-27 修复）。
function probeImage(image){
  try{
    const N=96,canvas=document.createElement("canvas");canvas.width=N;canvas.height=N;
    const ctx=canvas.getContext("2d",{willReadFrequently:true});
    ctx.drawImage(image,0,0,N,N);
    const {data}=ctx.getImageData(0,0,N,N);
    let satSum=0,lumSum=0,dark=0,bright=0,count=0;
    for(let i=0;i<data.length;i+=4){
      const r=data[i]/255,g=data[i+1]/255,b=data[i+2]/255;
      const max=Math.max(r,g,b),min=Math.min(r,g,b);
      const sat=max===0?0:(max-min)/max;
      const lum=0.2126*r+0.7152*g+0.0722*b;
      satSum+=sat;lumSum+=lum;
      if(lum<0.12)dark++;
      if(lum>0.78)bright++;
      count++;
    }
    return {satMean:satSum/count,lumMean:lumSum/count,darkRatio:dark/count,brightRatio:bright/count};
  }catch{return null;}
}
function analysisOfSource(){
  const p=state.sourceProbe;if(!p)return null;
  const {satMean,lumMean,darkRatio,brightRatio}=p;
  // 白模截图：背景近黑（大面积暗）+ 主体亮白（相当比例高亮）+ 几乎无彩度
  const clay=darkRatio>0.25&&brightRatio>0.10&&satMean<0.12;
  return {satMean,lumMean,darkRatio,brightRatio,isClay:clay};
}
function viewInfo(){return selectedItem()?.views?.find(row=>row.view===selectedView())||null;}
function passUrl(rel){return "/api/assets/file?rel="+encodeURIComponent(rel);}
function outputUrl(rel){return "/api/comfy/file?rel="+encodeURIComponent(rel.replace(/^outputs\//,""));}
function outputRel(task){return (task.output||"").split(",").map(s=>s.trim()).find(s=>s.startsWith("outputs/"))||"";}
function taskMode(task){try{return (typeof task.payload==="string"?JSON.parse(task.payload):task.payload)?._meta?.mode||"";}catch{return "";}}
function isUsablePass(rel){return !!rel && ACCEPT_PASS.has((rel.split(".").pop()||"").toLowerCase());}

async function api(url,options={}){
  const response=await fetch(url,options);
  const raw=await response.text();
  let data;
  try{data=JSON.parse(raw);}catch{throw new Error("服务返回了无法识别的数据");}
  if(!response.ok)throw new Error(data.error||`请求失败（${response.status}）`);
  return data;
}
function post(url,body){return api(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});}
function setBusy(button,busy,label){button.disabled=busy;if(label)button.textContent=label;}
function text(tag,value,className){const el=document.createElement(tag);el.textContent=value;if(className)el.className=className;return el;}
function clear(el){el.replaceChildren();}
function errorMessage(error){return error instanceof Error?error.message:String(error);}

async function refreshAll(){
  try{
    const [assets,tasks,comfy,ui]=await Promise.all([
      api("/api/assets"),api("/api/tasks?limit=300"),api("/api/comfy/status"),api("/api/ui/info")
    ]);
    state.assets=assets;state.tasks=tasks.tasks||[];state.comfy=comfy;state.ui=ui;
    if(state.sku&&!assets.items.some(item=>item.sku===state.sku))state.sku="";
    renderAll();
    loadStateExtras();
    selfCheckProviders();
  }catch(error){
    $("serviceStatus").className="service-status is-warn";
    $("serviceStatus").lastChild.textContent="渲染服务未连接";
    $("preflight").className="preflight is-error";
    $("preflight").textContent=offlineGuidance();
    $("generateButton").disabled=true;
    announce(errorMessage(error));
  }
}
async function refreshTasks(){
  try{state.tasks=(await api("/api/tasks?limit=300")).tasks||[];renderTasks();renderResults();renderHero();}
  catch(error){announce("刷新任务失败："+errorMessage(error));}
}
async function refreshServices(){
  try{
    state.comfy=await api("/api/comfy/status");
    renderService();renderServiceBox();renderRefPanel();renderPreflight();
  }catch(error){announce("服务状态更新失败："+errorMessage(error));}
}
async function refreshAssets(){
  state.assets=await api("/api/assets");renderProductSelect();renderSource();renderPassReadiness();renderHero();renderPreflight();renderAssetMatrix();
}
function renderAll(){renderProductSelect();renderSource();renderService();renderPassReadiness();renderPreflight();renderTasks();renderResults();renderHero();renderAssetMatrix();renderServiceBox();renderRefPanel();updateSizeHint();}

function renderProductSelect(){
  const select=$("productSelect");const existing=state.sku;clear(select);
  const first=new Option("选择产品或导入素材","");select.add(first);
  for(const item of state.assets.items){select.add(new Option(item.sku,item.sku));}
  select.value=existing;
}
let _thumbTimer=null;
function loadModelThumb(item,attempt){
  attempt=attempt||0;
  const box=$("modelThumb"),img=box&&box.querySelector("img");
  if(!box||!img)return;
  if(!item||!item.model){box.hidden=true;box.classList.remove("is-ready");return;}
  if(attempt===0)box.hidden=false;
  img.onload=()=>box.classList.add("is-ready");
  img.onerror=()=>{
    // 预览图是上传后由 Blender 在后台生成的，头几秒可能还没有 —— 退避重试几次
    if(attempt<4){clearTimeout(_thumbTimer);_thumbTimer=setTimeout(()=>loadModelThumb(item,attempt+1),900*(attempt+1));}
    else box.hidden=true;
  };
  img.src=`/api/model/thumb?sku=${encodeURIComponent(item.sku)}&r=${attempt}`;
}
/* ---------------- 3D 自由旋转预览（three.js 本地懒加载） ----------------
   网页只读后端已三角化、已验证的 GLB，原始 STEP/3DM 不直接喂浏览器。
   three.js 放在 web/vendor/，不走 CDN：本机网络对境外 CDN 不稳，
   预览器不该因为拉不到库就整个不可用。 */
const hero3d={renderer:null,scene:null,camera:null,controls:null,model:null,sku:"",raf:0,lib:null,loading:null,homeDist:4.2,bbox:null};
window.__hero3d=hero3d;   // 调试出口：可在控制台检查包围盒/姿态

async function loadThree(){
  if(hero3d.lib)return hero3d.lib;
  if(hero3d.loading)return hero3d.loading;
  hero3d.loading=(async()=>{
    const THREE=await import("/vendor/three/three.module.js");
    const {OrbitControls}=await import("/vendor/three/jsm/controls/OrbitControls.js");
    const {GLTFLoader}=await import("/vendor/three/jsm/loaders/GLTFLoader.js");
    hero3d.lib={THREE,OrbitControls,GLTFLoader};
    return hero3d.lib;
  })().catch(error=>{hero3d.loading=null;throw error;});
  return hero3d.loading;
}
function resize3D(){
  const canvas=$("heroCanvas");
  if(!hero3d.renderer||canvas.hidden)return;
  const host=canvas.parentElement;
  const w=host.clientWidth,h=host.clientHeight;
  if(!w||!h)return;
  hero3d.renderer.setSize(w,h,false);
  hero3d.camera.aspect=w/h;
  hero3d.camera.updateProjectionMatrix();
}
function stop3D(){if(hero3d.raf){cancelAnimationFrame(hero3d.raf);hero3d.raf=0;}}
/* ---------------- 部件拾取 ----------------
   用途：在 3D 里点中一个部件，高亮它并读出「名字 / 编号 / 三角面数」。
   ⚠️ 部件名来自源文件：Rhino 的 .3dm 常全是「物体.001」，STEP 往往带编号。
   名字不直观是数据本身的问题，所以界面把「高亮 + 编号 + 面数」一起给出，
   让用户靠高亮认出是哪个部件（后续可给它标别名/指定材质）。 */
function setPickedPart(mesh){
  if(hero3d.pickedMesh&&hero3d.pickedMesh!==mesh&&hero3d.matBase){
    hero3d.pickedMesh.material=hero3d.matBase;      // 还原上一个
  }
  hero3d.pickedMesh=mesh||null;
  if(mesh&&hero3d.matPick)mesh.material=hero3d.matPick;
  const box=$("partInfo");if(!box)return;
  if(!mesh){box.hidden=true;return;}
  box.hidden=false;
  const g=mesh.geometry;
  const tris=Math.round((g.index?g.index.count:(g.attributes.position||{count:0}).count)/3);
  const idx=hero3d.nameToIndex?hero3d.nameToIndex[normPartName(mesh.name)]:null;
  $("partName").textContent=mesh.name||"(未命名)";
  $("partMeta").textContent=`部件 #${idx==null?"—":idx} · ${tris.toLocaleString()} 个三角面`+
    (hero3d.partsTotal?` · 全模型共 ${hero3d.partsTotal} 个`:"")+
    (idx==null&&hero3d.partsNote?`（${hero3d.partsNote}）`:"");
}
function pickAt(clientX,clientY){
  const canvas=$("heroCanvas");
  if(!hero3d.raycaster||!hero3d.model||!hero3d.camera||!hero3d.lib)return null;
  const THREE=hero3d.lib.THREE;
  const rect=canvas.getBoundingClientRect();
  if(!rect.width||!rect.height)return null;
  const ndc=new THREE.Vector2(
    ((clientX-rect.left)/rect.width)*2-1,
    -((clientY-rect.top)/rect.height)*2+1);
  hero3d.raycaster.setFromCamera(ndc,hero3d.camera);
  const hits=hero3d.raycaster.intersectObject(hero3d.model,true);
  for(const h of hits){
    if(h.object&&h.object.isMesh&&h.object.visible)return h.object;
  }
  return null;
}
/* GLB 导出时 Blender 会把物体名里的 "." 去掉（物体.001 → 物体001），
   而 pass_manifest 里保留原点号。两边对不上就查不到编号，所以匹配前归一化。 */
function normPartName(s){return String(s||"").replace(/\./g,"").trim().toLowerCase();}
async function loadPartsIndex(sku){
  try{
    const d=await api(`/api/model/parts?sku=${encodeURIComponent(sku)}`);
    const rev={};
    for(const [idx,name] of Object.entries(d.parts||{}))rev[normPartName(name)]=Number(idx);
    hero3d.nameToIndex=rev;
    hero3d.partsTotal=d.count||0;
    hero3d.partsView=d.view||"";
    hero3d.partsNote=d.note||"";
  }catch(error){
    hero3d.nameToIndex=null;hero3d.partsTotal=0;hero3d.partsNote="部件索引读取失败";
  }
}
/* Blender 的 az/el 是 Z-up 约定，glTF/three.js 是 Y-up。
   轴向转换 (x,y,z)_blender → (x,z,-y)_gltf，于是方向向量：
     dir_three = ( sin(az)cos(el), sin(el), cos(az)cos(el) )
   这样 front(0,8) 落在 +Z、side(90,8) 落在 +X —— 与结构图的机位一一对应，
   用户在 3D 里摆好的角度，出结构图时就是同一个角度。 */
function blenderDir(THREE,azDeg,elDeg){
  const az=azDeg*Math.PI/180,el=elDeg*Math.PI/180;
  return new THREE.Vector3(Math.sin(az)*Math.cos(el),Math.sin(el),Math.cos(az)*Math.cos(el)).normalize();
}
function markActiveCam(key){
  for(const b of document.querySelectorAll("[data-cam]"))b.classList.toggle("is-active",b.dataset.cam===key);
}
function updateCamReadout(){
  const el=$("view3dReadout");if(!el||!hero3d.camera)return;
  const p=hero3d.camera.position;
  const r=Math.hypot(p.x,p.y,p.z)||1;
  const elev=Math.asin(Math.max(-1,Math.min(1,p.y/r)))*180/Math.PI;
  let az=Math.atan2(p.x,p.z)*180/Math.PI;
  if(az<0)az+=360;
  el.textContent=`方位 ${az.toFixed(0)}° · 仰角 ${elev.toFixed(0)}°`;
}
function setCameraToView(key){
  if(!hero3d.lib||!hero3d.camera)return;
  const {THREE}=hero3d.lib;
  const d=hero3d.homeDist||4.2;
  const a=VIEW_ANGLES_3D[key==="reset"?"3q4_left":key];
  if(!a)return;
  hero3d.camera.position.copy(blenderDir(THREE,a[0],a[1]).multiplyScalar(d));
  hero3d.controls.target.set(0,0,0);
  hero3d.controls.update();
  markActiveCam(key==="reset"?"3q4_left":key);
  updateCamReadout();
}
function toggleSpin(){
  if(!hero3d.controls)return;
  hero3d.controls.autoRotate=!hero3d.controls.autoRotate;
  hero3d.controls.autoRotateSpeed=1.6;
  $("camSpinButton").classList.toggle("is-active",hero3d.controls.autoRotate);
}
function tick3D(){
  const canvas=$("heroCanvas");
  if(!hero3d.renderer||canvas.hidden)return;
  hero3d.raf=requestAnimationFrame(tick3D);
  hero3d.controls.update();
  hero3d.renderer.render(hero3d.scene,hero3d.camera);
  updateCamReadout();
}
async function showModel3D(sku){
  const canvas=$("heroCanvas");
  canvas.hidden=false;
  let lib;
  try{lib=await loadThree();}
  catch(error){
    canvas.hidden=true;
    $("previewNote").textContent="3D 预览组件加载失败；已保留白模图档位。";
    return false;
  }
  const {THREE,OrbitControls,GLTFLoader}=lib;
  if(!hero3d.renderer){
    hero3d.renderer=new THREE.WebGLRenderer({canvas,antialias:true,alpha:true});
    hero3d.renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,2));
    hero3d.scene=new THREE.Scene();
    hero3d.camera=new THREE.PerspectiveCamera(35,1,0.01,5000);
    hero3d.controls=new OrbitControls(hero3d.camera,canvas);
    hero3d.controls.enableDamping=true;
    hero3d.controls.dampingFactor=0.08;
    hero3d.controls.enablePan=false;      // 只让用户转，不让它飘走
    hero3d.controls.minDistance=0.5;
    hero3d.controls.maxDistance=40;
    // 三点光：半球环境 + 主光 + 补光，白模才有体积感
    hero3d.scene.add(new THREE.HemisphereLight(0xffffff,0x9aa7ad,1.5));
    const key=new THREE.DirectionalLight(0xffffff,2.1);key.position.set(3,5,4);hero3d.scene.add(key);
    const fill=new THREE.DirectionalLight(0xffffff,0.85);fill.position.set(-4,-1,-3);hero3d.scene.add(fill);
    // 共享材质：2530 个部件各 new 一个太浪费；选中高亮时只替换那一个 mesh。
    hero3d.matBase=new THREE.MeshStandardMaterial({color:0xedeff0,roughness:0.58,metalness:0.03,side:THREE.DoubleSide});
    hero3d.matPick=new THREE.MeshStandardMaterial({color:0x4b8ef7,roughness:0.42,metalness:0.06,side:THREE.DoubleSide,emissive:0x1d4ed8,emissiveIntensity:0.32});
    hero3d.raycaster=new THREE.Raycaster();
  }
  if(hero3d.sku!==sku){
    if(hero3d.model){hero3d.scene.remove(hero3d.model);hero3d.model=null;}
    let gltf;
    try{gltf=await new GLTFLoader().loadAsync(`/api/model/glb?sku=${encodeURIComponent(sku)}`);}
    catch(error){
      hero3d.sku="";
      $("previewNote").textContent="预览模型还没准备好（后台正在转换），稍后重试或先看白模图。";
      return false;
    }
    const root=gltf.scene;
    // 自动取景：居中 + 归一化到统一尺度，任何尺寸的模型都刚好完整可见
    const box=new THREE.Box3().setFromObject(root);
    const size=box.getSize(new THREE.Vector3());
    const center=box.getCenter(new THREE.Vector3());
    const maxDim=Math.max(size.x,size.y,size.z)||1;
    const s=2.2/maxDim;
    hero3d.bbox={raw:[+size.x.toFixed(4),+size.y.toFixed(4),+size.z.toFixed(4)],rotatedX:false};
    // ★ 必须用 Group 承载，不能直接给 root 同时设 scale 和 position：
    //   矩阵是 T(position)·S(scale)，顶点先缩放再平移，拿「未缩放的世界坐标 center」
    //   当 position 会把模型整个推出画面（表现为 canvas 一片空白）。
    //   放进 Group 后，root.position 是 Group 的局部坐标，缩放由 Group 统一施加。
    root.position.sub(center);
    // 统一换成本地白模材质（共享实例）：GLB 不带材质，用 three 默认材质既灰又暗；
    // 更要紧的是**单面壳体**（STL/STEP 常见）在 FrontSide 下会「透视」成 X 光，
    // 必须 DoubleSide 才能看到完整外形。
    root.traverse(o=>{
      if(o.isMesh)o.material=hero3d.matBase;
    });
    hero3d.pickedMesh=null;
    setPickedPart(null);
    const holder=new THREE.Group();
    holder.add(root);
    holder.scale.setScalar(s);
    // ★ 这里**故意不做**任何「Z-up → Y-up」的启发式旋转。
    //   blender_pass.py 导出用的是 export_yup=True，模型已经是正确的 Y-up；
    //   再按包围盒最长边判断「要不要扶正」会把本来正确的模型转倒
    //   （实测：加了那句判断后，3D 里的姿态与 Blender 渲染的缩略图对不上）。
    //   判断姿态正确与否，只能拿「同一机位的 Blender 渲染图」对比，不能凭感觉。
    hero3d.bbox.reversed=false;
    hero3d.scene.add(holder);
    hero3d.model=holder;
    hero3d.sku=sku;
    // 按包围球 + 垂直 FOV 算相机距离，留 15% 余量
    const radius=0.5*Math.hypot(size.x,size.y,size.z)*s;
    const dist=radius/Math.sin(THREE.MathUtils.degToRad(35/2))*1.15;
    hero3d.homeDist=dist;
    setCameraToView("3q4_left");   // 默认与缩略图同角度，观感一致
    loadPartsIndex(sku);           // 部件索引（点选时用来显示「第几号部件」）
  }
  resize3D();stop3D();tick3D();
  return true;
}
function renderSource(){
  const item=selectedItem();const box=$("modelSummary");
  if(!item){box.textContent="还没有选择产品。";box.className="model-summary";$("imageSummary").textContent="上传一张产品照片或已有渲染图。";$("stageTitle").textContent="选择一个产品开始";state.sourceSize=null;state.sourceRelLoaded="";return;}
  const model=item.model;
  box.textContent=model?`${model.file} · ${model.size_h} · 已导入`:`${item.sku} · 已有结构图，未找到白模文件`;
  box.className="model-summary is-ready";
  $("imageSummary").textContent=item.source?`${item.source.file} · ${item.source.size_h} · 已导入`:`${item.sku} · 尚未上传产品图片`;
  $("imageSummary").className="model-summary"+(item.source?" is-ready":"");
  const rel=item.source?.rel||"";
  if(rel!==state.sourceRelLoaded){
    state.sourceRelLoaded=rel;state.sourceSize=null;state.sourceProbe=null;
    if(rel){const image=new Image();image.onload=()=>{
      if(state.sourceRelLoaded!==rel)return;
      state.sourceSize={width:image.naturalWidth,height:image.naturalHeight};
      state.sourceProbe=probeImage(image);
      renderPreflight();
    };image.onerror=()=>{if(state.sourceRelLoaded===rel)announce("产品图片无法读取，请重新上传。");};image.src=passUrl(rel);}
  }
  $("stageTitle").textContent=item.sku;
  if(state.thumbSku!==item.sku){state.thumbSku=item.sku;loadModelThumb(item,0);}
}
function renderService(){
  const el=$("serviceStatus");el.className="service-status "+(state.comfy.online?"is-ready":"is-warn");
  el.lastChild.textContent=state.comfy.online?"渲染服务已连接":"渲染服务未启动";
  $("referenceCapability").textContent=state.comfy.ipadapter_ok
    ?"已检测到参考图控制组件。参考图会作为图像条件参与生成，同时提取配色与影调；最终仍请按产品源素材核对轮廓和细节。"
    :"未检测到参考图控制组件。当前只把参考图的配色与影调写入提示词，原图本身不会参与生成。";
  renderProviderPanel();
}
function renderPreflight(){
  const box=$("preflight"),button=$("generateButton");const item=selectedItem(),row=viewInfo();const mode=getMode(),views=renderViews();
  const messages=[];let ready=true;
  if(!item){messages.push(mode==="image"?"先上传产品图片。":"先选择产品或导入白模。 ");ready=false;}
  if(!state.comfy.online){messages.push("ComfyUI 未连接；启动后可出图。");ready=false;}
  if(mode==="image"){
    if(item&&!item.source){messages.push("当前产品还没有源图片，请上传图片。");ready=false;}
    else if(item?.source&&!state.sourceSize){messages.push("正在读取图片尺寸…");ready=false;}
    else if(item?.source&&!sourceSize()){messages.push("按最长边缩到 1024 像素后，短边不足 256 像素；请上传比例更合适的图片。");ready=false;}
    messages.push("图片改图会参考原图构图与轮廓，但无法保证孔位、文字和结构精度；请对照原图检查。");
  }
  if(item&&mode==="controlled"){
    const missing=views.filter(view=>!isUsablePass(item.views?.find(row=>row.view===view)?.files?.depth));
    if(missing.length){messages.push(`${missing.map(view=>VIEW_ZH[view]).join("、")}缺少深度图。请在“任务”中逐个选择视角并生成结构图。`);ready=false;}
    const weak=views.filter(view=>{const files=item.views?.find(row=>row.view===view)?.files;return isUsablePass(files?.depth)&&!isUsablePass(files?.normal);});
    if(weak.length)messages.push(`${weak.map(view=>VIEW_ZH[view]).join("、")}缺少法线图：仍可出图，但细节约束较弱。`);
  }
  if(item&&mode==="explore")messages.push("外观探索只使用文字；可能改变产品形状、孔位和细节。");
  const batchCount=Number($("countSelect").value)*views.length;
  if(batchCount>=15)messages.push(`本次共 ${batchCount} 张，逐张生成；可能耗时较长，请保持网页与渲染服务运行。任务会保存，可在任务列表续跑。`);
  const refOn=!!(state.ref.strength&&state.ref.rel&&(state.ref.palette||[]).length);
  if(refOn){
    const iadapterOn=!!(state.comfy&&state.comfy.ipadapter_ok);
    messages.push(`参考图已接入（${state.ref.strength}）：配色 ${state.ref.palette.slice(0,3).map(p=>p.hex).join(" ")} 与影调写入提示词`
      +(iadapterOn?"；IPAdapter 已就绪，图片同时作为条件注入。":"；图像编码器未接入，图片本身不参与条件注入。"));
  }
  else if(state.ref.rel&&!state.ref.strength)messages.push("已上传参考图但强度选了「不使用」，本次不会生效。");
  if(ready&&mode==="controlled")messages.unshift("白模结构图和渲染服务已就绪。生成后请核对细节与文字。");
  if(ready&&mode==="image")messages.unshift(`产品图片已就绪 · ${state.sourceSize.width} × ${state.sourceSize.height}。`);
  box.className="preflight "+(ready?(mode==="controlled"||mode==="image"?"is-good":"is-warn"):(item?"is-warn":""));
  box.replaceChildren(...messages.map(message=>text("p",message)));
  const count=batchCount;
  button.textContent=state.running?`正在生成 ${state.runCount} 张…`:`开始生成 ${count} 张`;
  button.disabled=!ready||state.running;
  $("stageBadge").textContent=!item?"等待导入":mode==="image"?(ready?"图片已就绪":"等待图片"):mode==="explore"?"外观探索":ready?"结构图就绪":"结构图待准备";
  $("stageBadge").className="stage-badge "+(ready?"is-ready":"");
}
function renderPassReadiness(){
  $("passReadiness").closest(".drawer-section").hidden=state.sourceType==="image";
  for(const id of ["foldAssets","foldIou","foldCard"])$(id).hidden=state.sourceType==="image";
  if(state.sourceType==="image")return;
  const box=$("passReadiness");clear(box);const item=selectedItem(),row=viewInfo();
  if(!item){box.append(text("p","先选择产品。"));return;}
  box.append(text("p",`${item.sku} · ${VIEW_ZH[selectedView()]}`));
  for(const [role,label] of [["clay","白模预览"],["depth","深度图"],["normal","法线图"]]){
    box.append(text("p",`${label}：${isUsablePass(row?.files?.[role])?"已就绪":"缺失"}`));
  }
  const modelExt=(item.model?.ext||"").toLowerCase();
  // STEP/STP 首选 Blender 的 STEPper 插件（自带 OCC 内核，不用装 FreeCAD），
  // 插件缺失时才回退 FreeCAD；.3dm 靠 import_3dm 扩展。缺哪个才拦哪个。
  const stepReady=Boolean(state.ui.stepper||state.ui.freecad_cmd);
  const dmReady=Boolean(state.ui.import3dm);
  $("makePassButton").disabled=!item.model||!ACCEPT_MODEL.has(modelExt)||!state.ui.blender||(["stp","step"].includes(modelExt)&&!stepReady)||(modelExt==="3dm"&&!dmReady)||state.passJob?.status==="running";
  $("uploadPassButton").disabled=!item;
  if(!state.ui.blender)$("passJobStatus").textContent="未找到 Blender；可先在 Windows 安装 Blender 或上传已有结构图。";
  else if(["stp","step"].includes(modelExt)&&!stepReady)$("passJobStatus").textContent="STEP/STP 已保存；需要在 Blender 中启用 STEPper 插件（或安装 FreeCAD 并配置 FREECAD_CMD）才能生成结构图。";
  else if(modelExt==="3dm"&&!dmReady)$("passJobStatus").textContent="Rhino .3dm 需要 Blender 的 import_3dm 扩展（Blender 4.2+ 装成 bl_ext.user_default.import_3dm）；装上后可直接生成结构图。";
  else if(modelExt==="3dm")$("passJobStatus").textContent="Rhino .3dm 读取能力已就绪；若模型只有 NURBS 没有渲染网格，导入会失败并给出原因，此时请先在 Rhino 导出 GLB/OBJ。";
}
function renderHero(){
  const item=selectedItem(),row=viewInfo();const image=$("heroImage"),empty=$("heroEmpty");
  const overlay=$("compareLayer"),controls=$("compareControls");
  const canvas=$("heroCanvas");
  overlay.hidden=true;controls.hidden=true;$("hero").classList.remove("compare-mismatch");

  // ---- 3D 自由旋转档位：不吃 clay.png，直接用 GLB 在浏览器里转 ----
  if(state.preview==="model3d"){
    image.hidden=true;$("heroCaption").textContent="3D 自由旋转";
    $("view3dBar").hidden=false;
    if(item?.model){
      empty.hidden=true;
      $("previewNote").textContent=`${item.sku} · 拖动旋转 · 滚轮缩放 · 点下方按钮切 6 视图`;
      showModel3D(item.sku).catch(()=>{});
    }else{
      if(canvas){canvas.hidden=true;stop3D();}
      empty.hidden=false;
      $("view3dBar").hidden=true;
      $("previewNote").textContent="上传白模后可 3D 预览";
    }
    return;
  }
  $("view3dBar").hidden=true;
  if(canvas&&!canvas.hidden){canvas.hidden=true;stop3D();}
  // 图片模式没有白模可对比；成图与产品原图的比例通常不同，不提供像素级对比
  const compareAllowed=state.sourceType!=="image";
  const chosen=state.selectedTask&&state.tasks.find(t=>t.id===state.selectedTask);
  const latest=chosen&&outputRel(chosen)?chosen:state.tasks.find(t=>t.sku===state.sku&&t.view===selectedView()&&t.status==="done"&&outputRel(t));
  let url="",label="";
  if(state.preview==="result"){
    if(latest){url=outputUrl(outputRel(latest));label="生成结果 · #"+latest.id;}
  }else if(state.preview==="compare"&&compareAllowed&&latest&&isUsablePass(row?.files?.clay)){
    url=passUrl(row.files.clay);label="白模与成图对比";
    $("compareImage").src=outputUrl(outputRel(latest));overlay.hidden=false;controls.hidden=false;
    $("compareImage").width=image.width||1232;$("compareImage").height=image.height||752;
    setComparePosition();
  }else if(state.sourceType==="image"&&state.preview==="clay"&&item?.source){url=passUrl(item.source.rel);label="产品原图";}
  else if(state.preview==="depth"&&isUsablePass(row?.files?.depth)){url=passUrl(row.files.depth);label="深度结构图";}
  else if(state.preview==="clay"&&isUsablePass(row?.files?.clay)){url=passUrl(row.files.clay);label="白模预览";}
  if(url){image.src=url;image.alt=`${state.sku} ${VIEW_ZH[selectedView()]}${label}`;image.hidden=false;empty.hidden=true;}
  else{image.removeAttribute("src");image.hidden=true;empty.hidden=false;}
  $("heroCaption").textContent=label||({clay:state.sourceType==="image"?"产品原图":"白模预览",depth:"深度结构图",result:"生成结果",compare:"白模与成图对比"}[state.preview]);
  const fallbackNote=state.preview==="compare"
    ?(compareAllowed?"对比需要同视角的白模预览和成图。":"图片模式没有白模；出图后请对照“原图”查看保留程度。")
    :state.preview==="result"?"此视角尚无成图":state.preview==="depth"?"此视角尚无深度图":state.sourceType==="image"?"上传产品图片后可预览":"上传白模后可生成结构预览";
  $("previewNote").textContent=url?`${item?.sku||""} · ${VIEW_ZH[selectedView()]}`:fallbackNote;
  if(state.preview==="compare")syncCompareMode();
}
function setComparePosition(){
  const raw=Number($("compareRange").value);
  $("compareLayer").style.setProperty("--split",raw+"%");
  $("comparePercent").textContent=raw+"%";
}
function syncCompareMode(){
  if(state.preview!=="compare"||$("compareLayer").hidden)return;
  const base=$("heroImage"),result=$("compareImage");
  if(!base.complete||!result.complete||!base.naturalWidth||!result.naturalWidth)return;
  const baseRatio=base.naturalWidth/base.naturalHeight,resultRatio=result.naturalWidth/result.naturalHeight;
  const mismatch=Math.abs(baseRatio-resultRatio)>0.015;
  $("hero").classList.toggle("compare-mismatch",mismatch);
  $("compareControls").hidden=mismatch;
  if(mismatch)$("previewNote").textContent="白模与成图的比例不同，已改为左右并排；不能按像素重合判断结构。";
}
function renderResults(){
  const grid=$("resultsGrid");clear(grid);
  const rows=state.tasks.filter(task=>task.sku===state.sku&&(renderViews().length>1||task.view===selectedView())).slice(0,24);
  $("resultCount").textContent=`${rows.filter(t=>t.status==="done"&&outputRel(t)).length} 张已完成`;
  if(!rows.length){grid.append(text("div","出图后，候选图片会出现在这里。可以逐张查看和下载。","results-empty"));return;}
  for(const task of rows){
    const card=text("article","","result-card"),thumb=text("div","","result-thumb");const rel=outputRel(task);
    if(task.status==="done"&&rel){const img=document.createElement("img");img.src=outputUrl(rel);img.alt=`${task.sku} ${VIEW_ZH[task.view]||task.view} 候选图 ${task.variant+1}`;img.loading="lazy";img.width=320;img.height=200;thumb.append(img);}
    else{thumb.append(text("span",task.status==="failed"?"生成失败":task.status==="running"?"生成中…":"等待生成"));}
    thumb.append(text("span",({done:"已完成",running:"生成中",failed:"失败",pending:"待运行"})[task.status]||task.status,"task-state"));
    const body=text("div","","result-card-body");body.append(text("strong",`候选 ${task.variant+1} · ${VIEW_ZH[task.view]||task.view}`));
    if(task.err)body.append(text("small",task.err.slice(0,90)));
    const actions=text("div","","result-actions");
    if(rel){const preview=text("button","查看大图");preview.type="button";preview.onclick=()=>{state.selectedTask=task.id;setPreview("result");$("hero").scrollIntoView({behavior:"smooth",block:"center"});};actions.append(preview);
      if(state.sourceType!=="image"&&isUsablePass(viewInfo()?.files?.clay)){
        const compare=text("button","对比白模");compare.type="button";
        compare.onclick=()=>{state.selectedTask=task.id;setPreview("compare");$("hero").scrollIntoView({behavior:"smooth",block:"center"});};
        actions.append(compare);
      }
      const download=text("a","下载图片");download.href=outputUrl(rel);download.download=rel.split("/").pop();actions.append(download);}
    else if((task.status==="failed"||task.status==="pending")&&taskMode(task)){const run=text("button",task.status==="failed"?"重试本张":"运行本张");run.type="button";run.onclick=()=>runExisting(task);actions.append(run);}
    body.append(actions);card.append(thumb,body);grid.append(card);
  }
}
function renderTasks(){
  $("queueCount").textContent=String(state.tasks.filter(t=>t.status==="pending"||t.status==="running").length);
  const list=$("taskList");clear(list);const rows=state.tasks.slice(0,30);
  if(!rows.length){list.append(text("div","暂无任务"));return;}
  for(const task of rows){
    const row=text("div","","task-row"),main=text("div","","task-row-main");
    main.append(text("strong",`${task.sku} · ${VIEW_ZH[task.view]||task.view} · 候选 ${task.variant+1}`));
    main.append(text("span",({pending:"待运行",running:"生成中",done:"已完成",failed:"失败"})[task.status]||task.status));row.append(main);
    if(task.err)row.append(text("small",task.err.slice(0,180)));
    if((task.status==="pending"||task.status==="failed")&&taskMode(task)){
      const button=text("button",task.status==="failed"?"重试":"运行");button.type="button";button.onclick=()=>runExisting(task);row.append(button);
    }else if((task.status==="pending"||task.status==="failed")&&!taskMode(task)){
      row.append(text("small","旧版任务：请在旧控制台执行"));
    }else if(task.status==="running"){
      const button=text("button","更新结果");button.type="button";button.onclick=()=>pollOne(task.id);row.append(button);
    }
    list.append(row);
  }
}

function resolveOutputSize(view){
  const sel=$("sizeSelect")?$("sizeSelect").value:"auto";
  if(sel==="custom"){
    const m=/^\s*(\d{2,5})\s*[x×*,]\s*(\d{2,5})\s*$/i.exec(($("sizeCustom")||{}).value||"");
    if(m){
      // 对齐到 8 的倍数（扩散模型的 VAE 下采样要求），并限幅避免显存爆
      const w=Math.min(4096,Math.max(256,Math.round(Number(m[1])/8)*8));
      const h=Math.min(4096,Math.max(256,Math.round(Number(m[2])/8)*8));
      return {width:w,height:h,source:"custom"};
    }
    // 自定义没填对 → 不报错，静默退回跟随结构图
  }
  if(sel&&sel!=="auto"&&sel!=="custom"){
    const m=/^(\d+)x(\d+)$/.exec(sel);
    if(m)return {width:Number(m[1]),height:Number(m[2]),source:"preset"};
  }
  // auto：用**该机位结构图的实际像素尺寸**。
  // ★ 这一条很关键：曾经出图固定 1024×1024 而结构图是 1232×752，
  //   ControlNet 会把深度图缩放变形，产品直接被拉长。
  const row=(selectedItem()?.views||[]).find(v=>v.view===view);
  if(row&&row.size&&row.size.width&&row.size.height){
    return {width:row.size.width,height:row.size.height,source:"pass"};
  }
  return {width:1232,height:752,source:"fallback"};
}
function updateSizeHint(){
  const el=$("sizeHint");if(!el)return;
  const d=resolveOutputSize(selectedView());
  const src={pass:"该机位结构图的实际尺寸",preset:"你选的固定预设",custom:"你的自定义值",fallback:"结构图缺失，暂用默认 1232×752"}[d.source]||"";
  el.textContent=`本次实际出图 ${d.width} × ${d.height}（来源：${src}）。宽高会被对齐到 8 的倍数；与结构图同比例才不会把产品拉变形。`;
}
function buildPayload(sku,view,variant,mode){
  const description=$("description").value.trim();const style=STYLE[state.style],material=MATERIAL[$("materialSelect").value],lighting=LIGHT[$("lightSelect").value];
  const color=$("bodyColor").value;
  const useRef=!!(state.ref.strength&&state.ref.rel&&(state.ref.palette||[]).length);
  const refWord={L1_style:"overall mood and lighting",L2_material:"materials, colour palette and surface finish",L3_full:"materials, colour palette, lighting and composition"}[state.ref.strength]||"materials and colour palette";
  const refLine=useRef?`Borrow ${refWord} from a supplied reference photo. Its dominant colour palette is ${state.ref.palette.slice(0,4).map(p=>p.hex).join(", ")}. ${refToneWords(state.ref.bg,state.ref.lum)}. Keep the input product's silhouette.`:"";
  const positive=[`Professional high-end product photograph of ${sku}, ${VIEW_EN[view]}.`,`Main body: ${material}, color ${color}.`,lighting+".",style.text+".",
    "Premium commercial product photography, realistic material response, accurate camera perspective, crisp silhouette, fine controlled highlights, clean contact shadow.",
    description?`User's design requirements (retain exact intent): ${description}`:"",
    refLine,
    mode==="controlled"?"Follow the supplied depth map for the product silhouette and proportions. Do not invent openings, controls or markings.":mode==="image"?"Use the input product image as the primary composition and identity. Retain its camera angle, proportions, silhouette and component layout as closely as possible. Do not invent controls, openings, logos or text.":"Creative concept exploration; product geometry is not guaranteed."
  ].filter(Boolean).join(" ");
  const iadapterOn=!!(state.comfy&&state.comfy.ipadapter_ok);
  const refApplied=useRef?(iadapterOn?"ipadapter+prompt":"prompt_palette_only"):null;
  const dim=resolveOutputSize(view);
  const qualityKey=($("qualitySelect")||{}).value||"standard";
  const q=QUALITY[qualityKey]||QUALITY.standard;
  const payload={positive,negative:NEGATIVE,seed:(Math.floor(Date.now()/1000)+variant)%2147483647,
    width:dim.width,height:dim.height,
    _meta:{sku,view,variant,mode,ui_version:"2.0",style:state.style,description,
      output:{width:dim.width,height:dim.height,source:dim.source},
      quality:qualityKey,
      reference:useRef?{image:state.ref.rel,strength:state.ref.strength,palette:state.ref.palette.slice(0,4).map(p=>p.hex),applied:refApplied}:null}};
  // 质量档只作用于「结构约束出图」；图片改图有意保留它自己的 img2img 专参
  // （那套 denoise/steps 是配着 Canny 链路调出来的，不该被这里覆盖）。
  if(mode==="controlled"){payload.steps=q.steps;payload.cfg=q.cfg;}
  if(useRef&&iadapterOn)payload.ref_img=state.ref.rel;   // 装了 IPAdapter 才把图片真正送进去
  if(mode==="image"){
    const source=selectedItem()?.source,dimensions=sourceSize();
    if(!source||!dimensions)throw new Error("产品图片尚未就绪");
    payload.source_img=source.rel;payload.width=dimensions.width;payload.height=dimensions.height;
    payload.denoise=Number($("imageStrength").value)/100;
    // 白模/灰模截图：提示词要明确「把它变成有材质的成品」，负面词压住「保持灰色」
    const an=analysisOfSource();
    if(an&&an.isClay){
      payload.positive=payload.positive.replace(
        "Use the input product image as the primary composition and identity.",
        "The input is an unpainted clay/grey 3D model screenshot on a dark background. Convert it into a finished, fully materialised product: apply real surface materials, colour and finish to every surface. Use its silhouette and component layout as the primary composition and identity.");
      payload.negative=NEGATIVE+NEGATIVE_CLAY;
      payload._meta.input_kind="clay";
    }else{
      payload._meta.input_kind="photo";
    }
  }
  if(mode==="controlled"){
    const row=selectedItem()?.views?.find(itemView=>itemView.view===view);
    if(!isUsablePass(row?.files?.depth))throw new Error(`${VIEW_ZH[view]||view}缺少深度图`);
    payload.depth_img=row.files.depth;payload.depth_w=.65;
    if(isUsablePass(row.files.normal)){payload.normal_img=row.files.normal;payload.normal_w=.4;}
  }
  return payload;
}
async function generate(){
  renderPreflight();if($("generateButton").disabled)return;
  const sku=state.sku,views=renderViews(),perView=Number($("countSelect").value),count=perView*views.length,mode=getMode();
  const tasks=views.flatMap(view=>Array.from({length:perView},(_,variant)=>{const payload=buildPayload(sku,view,variant,mode);return{sku,view,variant,positive:payload.positive,negative:payload.negative,payload};}));
  state.running=true;state.runCount=count;renderPreflight();announce(`正在加入并生成 ${count} 张图片`);
  try{
    const inserted=await post("/api/tasks",{tasks});await refreshTasks();
    const ids=new Set(inserted.ids||[]);
    const created=state.tasks.filter(t=>ids.has(t.id)).sort((a,b)=>a.id-b.id);
    if(created.length!==count)throw new Error("任务已入队，但无法准确识别新任务。请在任务抽屉检查。 ");
    for(let i=0;i<created.length;i++){
      state.runCount=count-i;renderPreflight();
      try{await executeTask(created[i]);}
      catch(error){announce(`${VIEW_ZH[created[i].view]||created[i].view}候选 ${created[i].variant+1} 未完成：${errorMessage(error)}；继续下一张。`);}
    }
    announce(`${count} 张任务处理结束，请查看候选结果。`);
  }catch(error){announce("生成中断："+errorMessage(error));}
  finally{state.running=false;state.runCount=0;renderPreflight();await refreshTasks();}
}
async function executeTask(task){
  const payload=typeof task.payload==="string"?JSON.parse(task.payload):(task.payload||{});
  const mode=payload._meta?.mode;
  if(!["controlled","explore","image"].includes(mode))throw new Error("旧版任务请到旧控制台执行");
  if(mode==="image"&&(!payload.source_img||!payload.source_img.startsWith("source/")))throw new Error("图片改图任务缺少源图");
  if(mode==="controlled"){
    const assets=await api("/api/assets");const item=assets.items.find(x=>x.sku===task.sku);
    const row=item?.views?.find(x=>x.view===task.view);
    if(!isUsablePass(row?.files?.depth))throw new Error(`${task.sku} 的${VIEW_ZH[task.view]}缺少深度图，任务未执行`);
  }
  try{
    await post("/api/ui/comfy/submit",{id:task.id});await refreshTasks();
  }catch(error){
    await post("/api/task/status",{id:task.id,status:"failed",err:errorMessage(error)}).catch(()=>{});
    await refreshTasks();throw error;
  }
  for(let attempt=0;attempt<200;attempt++){
    await pause(3000);
    let result;
    try{result=await api(`/api/comfy/poll?id=${task.id}`);}catch(error){announce(`任务 #${task.id} 暂时无法查询：${errorMessage(error)}`);continue;}
    if(result.state==="done"){await refreshTasks();state.selectedTask=task.id;setPreview("result");return;}
    if(result.state==="error"){
      await post("/api/task/status",{id:task.id,status:"failed",err:result.error||"生成失败"}).catch(()=>{});
      await refreshTasks();throw new Error(`候选 ${task.variant+1}：${result.error||"生成失败"}`);
    }
    if(result.state==="offline")announce("ComfyUI 暂时断开；任务可能仍在运行。重新连接后到任务抽屉更新结果。 ");
  }
  announce(`任务 #${task.id} 仍在运行。请稍后到任务抽屉更新结果。`);
}
async function runExisting(task){
  if(state.running)return announce("当前已有一批任务在运行，请稍后重试。 ");
  state.running=true;state.runCount=1;renderPreflight();
  try{
    if(task.status==="failed")await post("/api/task/status",{id:task.id,status:"pending",err:""});
    await executeTask(task);
  }catch(error){announce("任务未完成："+errorMessage(error));}
  finally{state.running=false;state.runCount=0;renderPreflight();await refreshTasks();}
}
async function pollOne(id){
  try{const result=await api(`/api/comfy/poll?id=${id}`);await refreshTasks();announce(result.state==="done"?"图片已保存到结果区":`当前状态：${result.state}`);}
  catch(error){announce("更新失败："+errorMessage(error));}
}
function setPreview(kind){
  state.preview=kind;
  for(const button of document.querySelectorAll("[data-preview]")){const selected=button.dataset.preview===kind;button.classList.toggle("is-active",selected);button.setAttribute("aria-pressed",String(selected));}
  renderHero();
}
function setStyle(kind){
  state.style=kind;
  for(const button of document.querySelectorAll("[data-style]")){const selected=button.dataset.style===kind;button.classList.toggle("is-active",selected);button.setAttribute("aria-pressed",String(selected));}
}
function setSourceType(kind){
  if(kind===state.sourceType)return;
  state[state.sourceType==="image"?"imageCount":"modelCount"]=$("countSelect").value;
  state.sourceType=kind;state.selectedTask=null;setPreview("clay");
  $("countSelect").value=kind==="image"?state.imageCount:state.modelCount;
  for(const button of document.querySelectorAll("[data-source]")){
    const active=button.dataset.source===kind;button.classList.toggle("is-active",active);button.setAttribute("aria-pressed",String(active));
  }
  // 「对比」只在白模模式有意义：图片模式没有白模可以逐像素对照
  const compareButton=document.querySelector('[data-preview="compare"]');
  if(compareButton){compareButton.hidden=kind==="image";compareButton.disabled=kind==="image";}
  $("modelSourcePanel").hidden=kind==="image";$("imageSourcePanel").hidden=kind!=="image";
  $("modelModeSet").hidden=kind==="image";$("imageSettings").hidden=kind!=="image";
  $("viewField").hidden=kind==="image";$("batchField").hidden=kind==="image";
  $("sourcePreviewButton").textContent=kind==="image"?"原图":"白模";
  $("depthPreviewButton").hidden=kind==="image";
  $("heroEmpty").querySelector("p").textContent=kind==="image"?"上传产品图片。这里会显示原图与生成的候选图。":"导入白模，或选择已有产品。这里会显示结构预览与生成的图片。";
  document.querySelector(".row-fields").classList.toggle("is-single",kind==="image");
  const intro=$("refIntro");
  if(intro)intro.textContent=kind==="image"?"可选：再上传一张风格参考图，借鉴配色、材质与灯光。产品原图仍是出图主体。":"借鉴配色、材质与光照；结构约束仍以你的白模为准。未装参考图组件时，仅将提取的色彩与影调写入提示词。";
  renderSource();renderPassReadiness();renderPreflight();renderResults();renderHero();
}
function openDrawer(){lastFocus=document.activeElement;$("drawerBackdrop").hidden=false;$("queueDrawer").hidden=false;$("closeQueueButton").focus();refreshPassJob();}
function closeDrawer(){$("drawerBackdrop").hidden=true;$("queueDrawer").hidden=true;lastFocus?.focus();}
function trapDrawer(event){
  if($("queueDrawer").hidden)return;
  if(event.key==="Escape"){closeDrawer();return;}
  if(event.key!=="Tab")return;
  const focusables=[...$("queueDrawer").querySelectorAll("button:not(:disabled),select,input:not([hidden]),a[href]")].filter(el=>el.offsetParent!==null);
  if(!focusables.length)return;
  const first=focusables[0],last=focusables[focusables.length-1];
  if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
  else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
}
async function uploadModel(file){
  if(!file)return;
  const ext=(file.name.split(".").pop()||"").toLowerCase();
  if(["rhi","rhp","yak","3dmbak"].includes(ext))return announce(`${ext.toUpperCase()} 不是白模模型文件（${ext==="3dmbak"?"Rhino 备份文件":"Rhino 插件包"}），无法出结构图。请改用 .3dm，或在 Rhino 中导出 GLB/OBJ。`);
  if(![...ACCEPT_MODEL,"ksp","stp","step","3dm","c4d","max"].includes(ext))return announce("不支持这个白模格式。");
  setBusy($("chooseModelButton"),true,"正在导入…");
  try{
    const stem=file.name.replace(/\.[^.]+$/,"");
    const result=await api(`/api/assets/upload?rel=${encodeURIComponent(file.name)}&sku=${encodeURIComponent(stem)}`,{method:"POST",headers:{"Content-Type":"application/octet-stream"},body:file});
    state.thumbSku="";   // 换了模型 → 强制重拉预览图（后端已在上传成功时起了生成任务）
    await refreshAssets();
    const imported=state.assets.models.find(m=>m.rel===result.saved);
    state.sku=imported?.sku||result.sku||stem;
    renderAll();
    if(["stp","step"].includes(ext))announce(`${file.name} 已保存。${state.ui.stepper?"Blender 的 STEPper 插件已就绪，可直接生成结构图。":"需要在 Blender 中启用 STEPper 插件（或安装 FreeCAD）才能生成结构图。"}`);
    else if(ext==="3dm")announce(state.ui.import3dm
      ? `${file.name} 已导入。Rhino 读取能力已就绪，请选择视角并生成结构图。`
      : `${file.name} 已保存，但还缺 3DM 读取能力：请在 Blender 中安装并启用 import_3dm 扩展（Blender 4.2+ 装成 bl_ext.user_default.import_3dm）。仅有 NURBS 而无渲染网格时，请先在 Rhino 导出 GLB/OBJ。`);
    else if(!ACCEPT_MODEL.has(ext))announce(`${file.name} 已保存，但 ${ext.toUpperCase()} 需先转换为 GLB 或 OBJ，才能自动生成结构图。`);
    else announce(`${file.name} 已导入。请选择视角并生成结构图。`);
  }catch(error){announce("导入失败："+errorMessage(error));}
  finally{setBusy($("chooseModelButton"),false,"导入白模文件");$("modelFile").value="";}
}
async function uploadSource(file){
  if(!file)return;
  const ext=(file.name.split(".").pop()||"").toLowerCase();
  if(!["png","jpg","jpeg","webp"].includes(ext))return announce("产品图片只接受 PNG、JPG 或 WEBP。");
  if(file.size>20*1024*1024)return announce("图片不能超过 20 MB。");
  const button=$("chooseImageButton");setBusy(button,true,"正在上传…");
  try{
    const sku=state.sku||file.name.replace(/\.[^.]+$/,""),res=await api(`/api/source/upload?sku=${encodeURIComponent(sku)}&name=${encodeURIComponent(file.name)}`,{method:"POST",headers:{"Content-Type":"application/octet-stream"},body:file});
    state.sku=res.sku;state.sourceRelLoaded="";state.sourceSize=null;
    await refreshAssets();renderAll();loadExistingRef();announce(`${file.name} 已导入。描述材质与灯光后即可图片改图。`);
  }catch(error){announce("图片导入失败："+errorMessage(error));}
  finally{setBusy(button,false,"上传产品图片");$("imageFile").value="";}
}
async function uploadPass(files){
  const sku=state.sku,view=selectedView(),role=$("passRoleSelect").value;
  if(!sku)return announce("先选择产品。 ");
  if(!files.length)return;
  const button=$("uploadPassButton");setBusy(button,true,"正在上传…");
  try{
    const existing=viewInfo()?.files?.[role];
    if(existing&&!window.confirm(`此视角已有${{depth:"深度图",normal:"法线图",clay:"白模预览"}[role]}。确定用新文件替换吗？`))return;
    for(const file of files){
      const ext=(file.name.split(".").pop()||"").toLowerCase();if(!ACCEPT_PASS.has(ext))throw new Error("只接受 PNG、JPG、WEBP 或 BMP 结构图");
      if(existing&&existing.split(".").pop().toLowerCase()!==ext)throw new Error("替换已有结构图时，请上传相同格式的文件；当前是 "+existing.split(".").pop().toUpperCase());
      const rel=`${sku}/${view}/${role}.${ext}`;
      await api(`/api/assets/upload?rel=${encodeURIComponent(rel)}&sku=${encodeURIComponent(sku)}&view=${encodeURIComponent(view)}&overwrite=${existing?"1":"0"}`,{method:"POST",headers:{"Content-Type":"application/octet-stream"},body:file});
    }
    await refreshAssets();announce("结构图已上传。请在预览中核对对应视角。 ");
  }catch(error){announce("结构图上传失败："+errorMessage(error));}
  finally{setBusy(button,false,"上传选定类型");$("passFiles").value="";}
}
async function makePass(){
  try{await post("/api/ui/pass/start",{sku:state.sku,view:selectedView(),model:selectedItem()?.model?.rel||""});announce("正在生成结构图。 ");await refreshPassJob();}
  catch(error){announce("无法生成结构图："+errorMessage(error));}
}
async function refreshPassJob(){
  try{
    state.passJob=await api("/api/ui/pass/status");
    if(state.passJob.status==="running"){$("passJobStatus").textContent=`${state.passJob.sku} · ${VIEW_ZH[state.passJob.view]}：正在生成结构图…`;setTimeout(refreshPassJob,2500);}
    else if(state.passJob.status==="done"){$("passJobStatus").textContent="结构图已生成。";await refreshAssets();}
    else if(state.passJob.status==="failed"){$("passJobStatus").textContent="结构图生成失败："+state.passJob.message;}
    renderPassReadiness();
  }catch(error){$("passJobStatus").textContent="无法读取结构图任务状态："+errorMessage(error);}
}

$("productSelect").addEventListener("change",event=>{state.sku=event.target.value;state.selectedTask=null;renderSource();renderPassReadiness();renderPreflight();renderResults();renderHero();loadExistingRef();});
document.querySelectorAll("[data-source]").forEach(el=>el.addEventListener("click",()=>setSourceType(el.dataset.source)));
$("imageStrength").addEventListener("input",event=>{$("imageStrengthValue").value=event.target.value+"%";renderPreflight();});
$("viewSelect").addEventListener("change",()=>{state.selectedTask=null;renderPassReadiness();renderPreflight();renderResults();renderHero();});
$("countSelect").addEventListener("change",renderPreflight);
$("sizeSelect").addEventListener("change",()=>{
  const isCustom=$("sizeSelect").value==="custom";
  $("sizeCustomField").hidden=!isCustom;
  if(isCustom)$("sizeCustom").focus();
  updateSizeHint();renderPreflight();
});
$("sizeCustom").addEventListener("input",()=>{updateSizeHint();renderPreflight();});
$("qualitySelect").addEventListener("change",renderPreflight);
/* ---- 出图视角：任意多选 ---- */
function buildViewChecks(){
  const box=$("viewChecks");if(!box||box.dataset.built==="1")return;
  clear(box);
  for(const v of ALL_VIEWS){
    const label=document.createElement("label");
    label.className="view-check";
    const cb=document.createElement("input");
    cb.type="checkbox";cb.dataset.view=v;cb.checked=(v==="front");
    label.append(cb,document.createTextNode(VIEW_ZH[v]||v));
    box.append(label);
  }
  box.dataset.built="1";
  box.addEventListener("change",()=>{renderPreflight();renderResults();});
}
function setViewChecks(views){
  const box=$("viewChecks");if(!box)return;
  for(const cb of box.querySelectorAll('input[type="checkbox"]'))cb.checked=views.includes(cb.dataset.view);
  renderPreflight();renderResults();
}
buildViewChecks();
$("viewPickPreview").addEventListener("click",()=>setViewChecks([selectedView()]));
$("viewPickStandard").addEventListener("click",()=>setViewChecks(STANDARD_VIEWS));
$("viewPickAll").addEventListener("click",()=>setViewChecks(ALL_VIEWS));
$("viewPickNone").addEventListener("click",()=>setViewChecks([]));
document.querySelectorAll('input[name="mode"]').forEach(el=>el.addEventListener("change",renderPreflight));
document.querySelectorAll("[data-style]").forEach(el=>el.addEventListener("click",()=>setStyle(el.dataset.style)));
document.querySelectorAll("[data-preview]").forEach(el=>el.addEventListener("click",()=>setPreview(el.dataset.preview)));
$("heroCanvas").addEventListener("dblclick",()=>{          // 双击复位视角
  setCameraToView("reset");
});
for(const b of document.querySelectorAll("[data-cam]")){
  b.addEventListener("click",()=>{
    if(b.dataset.cam==="spin"){toggleSpin();return;}
    setCameraToView(b.dataset.cam);
  });
}
/* 部件拾取：必须区分「拖动旋转」和「点击选择」——
   按下到抬起位移超过阈值就当成旋转，不做拾取。 */
let _pickDown=null;
$("heroCanvas").addEventListener("pointerdown",e=>{_pickDown={x:e.clientX,y:e.clientY};});
$("heroCanvas").addEventListener("pointerup",e=>{
  if(!_pickDown)return;
  const moved=Math.hypot(e.clientX-_pickDown.x,e.clientY-_pickDown.y);
  _pickDown=null;
  if(moved>5)return;                       // 拖动过 → 那是旋转
  if(state.preview!=="model3d")return;
  setPickedPart(pickAt(e.clientX,e.clientY));   // 点空白处即取消选择
});
$("partClear").addEventListener("click",()=>setPickedPart(null));
window.addEventListener("resize",()=>{if(state.preview==="model3d")resize3D();});
$("bodyColor").addEventListener("input",event=>{$("bodyColorValue").textContent=event.target.value.toUpperCase();});
$("refreshButton").addEventListener("click",refreshAll);
$("refreshTasksButton").addEventListener("click",refreshTasks);
$("generateButton").addEventListener("click",generate);
$("chooseModelButton").addEventListener("click",()=>$("modelFile").click());
$("modelFile").addEventListener("change",event=>uploadModel(event.target.files[0]));
$("chooseImageButton").addEventListener("click",()=>$("imageFile").click());
$("imageFile").addEventListener("change",event=>uploadSource(event.target.files[0]));
$("hero").addEventListener("dragover",event=>{event.preventDefault();$("hero").classList.add("is-dropping");});
$("hero").addEventListener("dragleave",()=>$("hero").classList.remove("is-dropping"));
$("hero").addEventListener("drop",event=>{event.preventDefault();$("hero").classList.remove("is-dropping");const file=event.dataTransfer?.files?.[0];if(file)(state.sourceType==="image"?uploadSource:uploadModel)(file);});
$("openQueueButton").addEventListener("click",openDrawer);
$("closeQueueButton").addEventListener("click",closeDrawer);
$("drawerBackdrop").addEventListener("click",closeDrawer);
document.addEventListener("keydown",trapDrawer);
$("makePassButton").addEventListener("click",makePass);
$("uploadPassButton").addEventListener("click",()=>$("passFiles").click());
$("passFiles").addEventListener("change",event=>uploadPass([...event.target.files]));
$("runPendingButton").addEventListener("click",async()=>{
  if(state.running)return announce("已有任务在运行。 ");
  const pending=state.tasks.filter(t=>t.status==="pending"&&taskMode(t)).sort((a,b)=>a.id-b.id);
  if(!pending.length)return announce("没有待处理任务。 ");
  state.running=true;state.runCount=pending.length;renderPreflight();
  try{for(let i=0;i<pending.length;i++){state.runCount=pending.length-i;renderPreflight();try{await executeTask(pending[i]);}catch(error){announce("任务 #"+pending[i].id+" 失败："+errorMessage(error));}}}
  finally{state.running=false;state.runCount=0;renderPreflight();await refreshTasks();}
});
$("heroImage").addEventListener("error",()=>{ $("heroImage").hidden=true;$("heroEmpty").hidden=false;$("previewNote").textContent="预览图无法读取，请刷新或检查文件。";});
$("heroImage").addEventListener("load",syncCompareMode);
$("compareImage").addEventListener("load",syncCompareMode);
$("compareImage").addEventListener("error",()=>{$("compareLayer").hidden=true;$("compareControls").hidden=true;$("previewNote").textContent="成图无法读取，暂时不能对比；请检查输出文件。";});
$("compareRange").addEventListener("input",setComparePosition);

/* =========================================================
   v1.9 重构新增：投放区矩阵 / 服务详情 / 参数卡 / 看板 / 变更记录 / 对齐校验(IoU)
   ========================================================= */
const CARD_MATERIAL = {
  matte_plastic:{type:"ABS",finish:"fine_sandblast",roughness:.75,metallic:0},
  glossy_plastic:{type:"ABS",finish:"glossy",roughness:.18,metallic:0},
  soft_touch:{type:"ABS",finish:"soft_touch",roughness:.6,metallic:0},
  brushed_aluminum:{type:"aluminum",finish:"anodized_brushed",roughness:.35,metallic:1},
  sandblasted_metal:{type:"aluminum",finish:"sandblasted",roughness:.55,metallic:1},
  gunmetal:{type:"steel",finish:"satin_gunmetal",roughness:.3,metallic:1},
  polished_metal:{type:"stainless",finish:"polished",roughness:.08,metallic:1},
  chrome:{type:"chrome",finish:"mirror",roughness:.02,metallic:1},
  carbon_fiber:{type:"composite",finish:"carbon_weave",roughness:.25,metallic:.1},
  rubber:{type:"TPE",finish:"matte_rubber",roughness:.9,metallic:0},
  leather:{type:"leather",finish:"fine_grain",roughness:.7,metallic:0},
  wood:{type:"wood",finish:"satin_grain",roughness:.6,metallic:0}
};
const CARD_BG = {
  studio:{type:"gradient_gray",from:"#F5F6F7",to:"#DDE1E4"},
  white:{type:"pure_white",from:"#FFFFFF",to:"#F2F4F5"},
  dark:{type:"charcoal_gradient",from:"#3A3F44",to:"#22262A"}
};
const CARD_LIGHT = {soft:"studio_softbox_3point",top:"top_soft",dramatic:"backlight_dramatic",natural:"natural_window"};

function renderAssetMatrix(){
  const box=$("assetMatrix");if(!box)return;clear(box);
  const items=state.assets.items||[];
  if(!items.length){box.append(text("div","投放区还没有素材。导入白模后会出现在这里。"));return;}
  for(const item of items){
    const views=item.views||[],done=views.filter(v=>v.ok).length;
    const row=text("div","","matrix-row"+(done?" is-ready":""));
    const head=text("div","","matrix-head");
    head.append(text("strong",item.sku));
    head.append(text("span",views.length?`${done}/${views.length} 机位就绪`:"尚无结构图","fold-hint"));
    row.append(head);
    const wrap=text("div","","matrix-views");
    for(const v of views){
      const miss=v.missing||[];
      wrap.append(text("span",`${VIEW_ZH[v.view]||v.view}${miss.length?"（缺 "+miss.join("/")+"）":""}`,
        "view-chip "+(v.ok?"is-ready":miss.length<3?"is-part":"")));
    }
    if(!views.length)wrap.append(text("span","待出结构图","view-chip"));
    row.append(wrap);box.append(row);
  }
}

function renderServiceBox(){
  const box=$("serviceBox");if(!box)return;clear(box);
  const c=state.comfy||{},ui=state.ui||{};
  box.append(text("p",`ComfyUI：${c.online?"在线":"离线"}${c.version?" · "+c.version:""}${c.url?" · "+c.url:""}`));
  if(c.device)box.append(text("p",`显卡：${c.device} · 显存 ${c.vram_free_gb??"—"}/${c.vram_total_gb??"—"} GB`));
  box.append(text("p",`底模：${(c.checkpoints||[]).join("  /  ")||"—"}`));
  box.append(text("p",`首选底模：${c.preferred_checkpoint||"—"}${c.preferred_ok===false?"（不可用，将自动切 fallback）":"（可用）"}`));
  box.append(text("p",`ControlNet：${(c.controlnets||[]).join("  /  ")||"—"}`));
  box.append(text("p",`Blender：${ui.blender?"已找到 · "+ui.blender_path:"未找到（无法自动出结构图）"}`));
  box.append(text("p",`结构图脚本：${ui.blender_script?"已就位":"缺失 scripts/blender_pass.py"}`));
  const hint=$("serviceHint");if(hint)hint.textContent=c.online?"在线":"离线";
}

function renderBoard(){
  const box=$("boardBox");if(!box)return;clear(box);
  const b=state.board;
  if(!b||!b.phases){box.append(text("p","未能载入看板数据。"));return;}
  for(const p of b.phases){
    const item=text("div","","board-item"),head=text("div","","bi-head");
    head.append(text("strong",`${p.id} · ${p.name}${p.gate?"  [硬门槛]":""}`));
    head.append(text("span",p.status||"未开始","fold-hint"));
    item.append(head);
    item.append(text("small",`目标：${p.goal||"—"}`));
    if(p.accept)item.append(text("small",`验收：${p.accept}`));
    box.append(item);
  }
}

function renderChangelog(){
  const box=$("changelogBox");if(!box)return;clear(box);
  const rows=state.changelog||[];
  if(!rows.length){box.append(text("p","未读到变更记录。"));return;}
  for(const r of rows.slice(0,30)){
    const item=text("div","","cl-item"),head=text("div","","cl-head");
    head.append(text("span",r.version||"","fold-hint"));
    head.append(text("span",r.type||"","cl-tag "+(r.type||"")));
    head.append(text("span",r.date||"","fold-hint"));
    item.append(head);
    item.append(text("small",(r.summary||"").slice(0,300)));
    if(r.reason)item.append(text("small","触发："+r.reason));
    box.append(item);
  }
}

function buildCard(){
  const item=selectedItem(),body=CARD_MATERIAL[$("materialSelect").value]||CARD_MATERIAL.matte_plastic;
  const color=$("bodyColor").value.toUpperCase();
  const views=item&&item.views&&item.views.length?item.views.map(v=>v.view):[selectedView()];
  return {
    asset:{model:item?.model?.path||"",category:"",sku:state.sku,views},
    material:{body:{type:body.type,finish:body.finish,color,roughness:body.roughness,metallic:body.metallic}},
    lighting:{scheme:CARD_LIGHT[$("lightSelect").value]||"studio_softbox_3point",shadow:"soft_contact"},
    camera:{focal:85,height:"product_level",perspective:"mild_tele"},
    background:{...CARD_BG[state.style]},
    reference:(state.ref.rel&&state.ref.strength)?{
      image:state.ref.rel, strength:state.ref.strength,
      ...(state.ref.strength==="L2_material"?{target_part:"body"}:{})
    }:{image:"",strength:""},
    output:{resolution:[1024,1024],count:Number($("countSelect").value),upscale:1,lang:"CN"},
    _seed_base:Math.floor(Date.now()/1000)%2000000,
    _depth_w:.65,_normal_w:.4,_timeout:600
  };
}
function applyCard(card){
  if(!card||!card.material)throw new Error("参数卡内容不完整");
  const b=card.material.body||{};
  if(b.color){$("bodyColor").value=b.color.toLowerCase();$("bodyColorValue").textContent=b.color.toUpperCase();}
  const matKey=Object.keys(CARD_MATERIAL).find(k=>CARD_MATERIAL[k].finish===b.finish);
  if(matKey)$("materialSelect").value=matKey;
  const lt=Object.keys(CARD_LIGHT).find(k=>CARD_LIGHT[k]===card.lighting?.scheme);
  if(lt)$("lightSelect").value=lt;
  const st=Object.keys(CARD_BG).find(k=>CARD_BG[k].type===card.background?.type);
  if(st)setStyle(st);
  const cnt=card.output?.count;
  if(cnt&&[...$("countSelect").options].some(o=>o.value===String(cnt)))$("countSelect").value=String(cnt);
}
async function loadCard(){
  if(!state.sku)return announce("先选择产品。");
  try{
    const card=await api("/api/card?sku="+encodeURIComponent(state.sku));
    applyCard(card);
    $("cardPreview").textContent=JSON.stringify(card,null,2);
    renderPreflight();announce(`已载入参数卡：${state.sku}`);
  }catch(error){$("cardPreview").textContent="（未找到 "+state.sku+" 的参数卡）";announce("载入失败："+errorMessage(error));}
}
async function saveCard(){
  if(!state.sku)return announce("先选择产品。");
  try{
    const card=buildCard();
    const result=await post("/api/card",card);
    $("cardPreview").textContent=JSON.stringify(card,null,2);
    announce(`参数卡已保存：${result.sku||state.sku}`);
  }catch(error){announce("保存失败："+errorMessage(error));}
}

/* ---------- 对齐校验：轮廓 IoU ---------- */
function loadImage(url){
  return new Promise((resolve,reject)=>{
    const img=new Image();
    img.onload=()=>resolve(img);
    img.onerror=()=>reject(new Error("图片无法读取："+url));
    img.src=url;
  });
}
function toGrayMask(img,w,h,useBgSubtract,threshold){
  const canvas=document.createElement("canvas");canvas.width=w;canvas.height=h;
  const ctx=canvas.getContext("2d",{willReadFrequently:true});
  ctx.drawImage(img,0,0,w,h);
  const data=ctx.getImageData(0,0,w,h).data,mask=new Uint8Array(w*h);
  if(!useBgSubtract){
    for(let i=0;i<w*h;i++){const lum=(data[i*4]+data[i*4+1]+data[i*4+2])/3;mask[i]=lum>128?1:0;}
    return mask;
  }
  const corners=[[2,2],[w-3,2],[2,h-3],[w-3,h-3]];
  let br=0,bg=0,bb=0;
  for(const [x,y] of corners){const o=(y*w+x)*4;br+=data[o];bg+=data[o+1];bb+=data[o+2];}
  br/=4;bg/=4;bb/=4;
  const limit=threshold*threshold*3;
  for(let i=0;i<w*h;i++){
    const dr=data[i*4]-br,dg=data[i*4+1]-bg,db=data[i*4+2]-bb;
    mask[i]=(dr*dr+dg*dg+db*db>limit)?1:0;
  }
  return mask;
}
async function computeIoU(){
  const box=$("iouResult");clear(box);
  const row=viewInfo();
  const alphaRel=row?.files?.alpha;
  if(!state.sku||!alphaRel){box.append(text("p","当前机位没有 alpha.png（白模掩膜），请先生成结构图。"));return;}
  const task=state.tasks.find(t=>t.sku===state.sku&&t.view===selectedView()&&t.status==="done"&&outputRel(t));
  if(!task){box.append(text("p","当前机位还没有已完成的成图。"));return;}
  const threshold=Number($("iouThreshold").value);
  box.append(text("p","计算中…"));
  try{
    const W=384,H=Math.round(W*752/1232);
    const [imgA,imgB]=await Promise.all([loadImage(passUrl(alphaRel)),loadImage(outputUrl(outputRel(task)))]);
    const maskA=toGrayMask(imgA,W,H,false,0);
    const maskB=toGrayMask(imgB,W,H,true,threshold);
    let inter=0,union=0,aCount=0,bCount=0;
    for(let i=0;i<W*H;i++){
      const a=maskA[i],b=maskB[i];
      if(a)aCount++;if(b)bCount++;
      if(a&&b)inter++;
      if(a||b)union++;
    }
    const iou=union?inter/union:0;
    const pass=iou>=0.90;
    clear(box);
    const line=text("p");
    line.append(text("strong",iou.toFixed(3)));
    line.append(text("span",`  门槛 0.900 · ${pass?"通过":"未达标"}`,pass?"badge-ok":"badge-warn"));
    box.append(line);
    box.append(text("p",`白模面积 ${(aCount/(W*H)*100).toFixed(1)}% ｜ 成图剪影 ${(bCount/(W*H)*100).toFixed(1)}% ｜ 交集 ${(inter/(W*H)*100).toFixed(1)}%`));
    box.append(text("p",`任务 #${task.id} ｜ 背景容差 ${threshold}`));
    // 叠加预览：绿=只白模有，红=只成图有，黄=重合
    const canvas=document.createElement("canvas");canvas.width=W;canvas.height=H;
    canvas.style.width="100%";canvas.style.borderRadius="8px";canvas.style.marginTop="8px";
    const ctx=canvas.getContext("2d"),out=ctx.createImageData(W,H);
    for(let i=0;i<W*H;i++){
      const a=maskA[i],b=maskB[i];
      let r=244,g=246,bl=248;
      if(a&&b){r=255;g=214;bl=102;}
      else if(a){r=54;g=126;bl=91;}
      else if(b){r=179;g=69;bl=59;}
      out.data[i*4]=r;out.data[i*4+1]=g;out.data[i*4+2]=bl;out.data[i*4+3]=255;
    }
    ctx.putImageData(out,0,0);box.append(canvas);
    box.append(text("p","绿=仅白模有　红=仅成图有　黄=重合"));
  }catch(error){
    clear(box);box.append(text("p","计算失败："+errorMessage(error)));
  }
}

/* ---------- 抽屉折叠：展开时按需载入 ---------- */
async function loadStateExtras(){
  try{
    const s=await api("/api/state");
    state.board=s.board;state.doc=s.doc;renderBoard();
  }catch(error){$("boardBox").textContent="看板载入失败："+errorMessage(error);}
  try{
    const cl=await api("/api/changelog");state.changelog=cl.rows||[];renderChangelog();
  }catch(error){$("changelogBox").textContent="变更记录载入失败："+errorMessage(error);}
}
function wireFolds(){
  const map={foldAssets:()=>renderAssetMatrix(),foldIou:()=>{},foldCard:()=>{},
             foldService:()=>renderServiceBox(),foldBoard:()=>{if(!state.board)loadStateExtras();else renderBoard();},
             foldChangelog:()=>{if(!state.changelog)loadStateExtras();else renderChangelog();}};
  for(const [id,fn] of Object.entries(map)){
    const el=$(id);if(!el)continue;
    el.addEventListener("toggle",()=>{if(el.open)fn();});
  }
}
for(const el of ["iouRunButton","loadCardButton","saveCardButton"]){
  const button=$(el);if(!button)continue;
  if(el==="iouRunButton")button.addEventListener("click",computeIoU);
  if(el==="loadCardButton")button.addEventListener("click",loadCard);
  if(el==="saveCardButton")button.addEventListener("click",saveCard);
}
$("iouThreshold")?.addEventListener("input",event=>{$("iouThresholdValue").textContent=event.target.value;});
wireFolds();

/* =========================================================
   参考图（v1.9）：只借配色 / 材质 / 光照，不替换形状（文档 §三.3）
   当前实现：浏览器内提取调色板与影调 → 翻成提示词；
   图像编码器（IPAdapter）未接入，图片本身不参与条件注入 —— 界面如实说明。
   ========================================================= */
function refToneWords(bg,lum){
  const parts=[];
  if(bg>200)parts.push("seamless bright background, high-key lighting");
  else if(bg<70)parts.push("deep dark background, low-key dramatic lighting");
  else parts.push("clean mid-grey seamless background, soft studio lighting");
  if(lum<60)parts.push("muted low-key tonal range");
  else if(lum>185)parts.push("bright airy tonal range");
  return parts.join(", ");
}
function extractPalette(img){
  const W=96,H=72,c=document.createElement("canvas");c.width=W;c.height=H;
  const ctx=c.getContext("2d",{willReadFrequently:true});
  ctx.drawImage(img,0,0,W,H);
  const d=ctx.getImageData(0,0,W,H).data,buckets=new Map();
  let lumSum=0,satSum=0;
  for(let i=0;i<W*H;i++){
    const r=d[i*4],g=d[i*4+1],b=d[i*4+2];
    lumSum+=0.2126*r+0.7152*g+0.0722*b;
    const mx=Math.max(r,g,b),mn=Math.min(r,g,b);
    satSum+=mx?(mx-mn)/mx:0;
    const key=((r>>5)<<6)|((g>>5)<<3)|(b>>5);
    const e=buckets.get(key)||{n:0,r:0,g:0,b:0};
    e.n++;e.r+=r;e.g+=g;e.b+=b;buckets.set(key,e);
  }
  const total=W*H;
  const palette=[...buckets.values()].sort((a,b)=>b.n-a.n).slice(0,6).map(e=>({
    hex:"#"+[e.r/e.n,e.g/e.n,e.b/e.n].map(v=>Math.round(v).toString(16).padStart(2,"0")).join("").toUpperCase(),
    share:+(e.n/total*100).toFixed(1)
  }));
  const corner=(x,y)=>{const o=(y*W+x)*4;return 0.2126*d[o]+0.7152*d[o+1]+0.0722*d[o+2];};
  const bg=(corner(2,2)+corner(W-3,2)+corner(2,H-3)+corner(W-3,H-3))/4;
  return {palette,lum:lumSum/total,sat:satSum/total,bg};
}
function renderRefPanel(){
  const thumb=$("refThumb"),pal=$("refPalette");
  if(thumb){
    if(state.ref.rel){clear(thumb);const im=document.createElement("img");im.src=passUrl(state.ref.rel);im.alt="参考图";im.width=92;im.height=92;thumb.append(im);}
    else thumb.textContent="未选择";
  }
  if(pal){
    clear(pal);
    for(const p of (state.ref.palette||[])){
      const b=document.createElement("button");b.type="button";
      b.title=`${p.hex}（占比 ${p.share}%）— 点一下设为主体色`;
      b.setAttribute("aria-label",`将主体色设为 ${p.hex}，参考图占比 ${p.share}%`);
      const i=document.createElement("i");i.style.background=p.hex;b.append(i);
      b.onclick=()=>{$("bodyColor").value=p.hex.toLowerCase();$("bodyColorValue").textContent=p.hex;announce(`主体色已设为 ${p.hex}`);};
      pal.append(b);
    }
  }
  const apply=$("applyPaletteButton");
  if(apply)apply.disabled=!(state.ref.palette||[]).length;
  const note=$("refNote");
  if(note){
    const iadapterOn=!!(state.comfy&&state.comfy.ipadapter_ok);
    if(!state.ref.rel)note.textContent="上传参考图后会自动提取调色板。";
    else note.textContent=`已提取 ${state.ref.palette.length} 个主色 · ${refToneWords(state.ref.bg,state.ref.lum)}｜`
      +(iadapterOn
        ? "参考图已作为图像条件注入，配色与影调同时写入提示词；请核对最终形状。"
        : "图像编码器未接入，暂只把配色与影调写进提示词；图片本身不参与条件注入。");
  }
  if($("refStrength"))$("refStrength").value=state.ref.strength||"";
}
async function uploadReference(file){
  if(!file)return;
  const ext=(file.name.split(".").pop()||"").toLowerCase();
  if(!["png","jpg","jpeg","webp","tif","tiff","bmp"].includes(ext))return announce("参考图只接受 PNG / JPG / WEBP / BMP。");
  const button=$("chooseRefButton");setBusy(button,true,"读取中…");
  try{
    const url=URL.createObjectURL(file);
    const img=await loadImage(url);
    const info=extractPalette(img);
    const sku=state.sku||"_未指定";
    const res=await api(`/api/refs/upload?sku=${encodeURIComponent(sku)}&name=${encodeURIComponent(file.name)}`,
      {method:"POST",headers:{"Content-Type":"application/octet-stream"},body:file});
    URL.revokeObjectURL(url);
    state.ref.rel=res.saved;state.ref.palette=info.palette;state.ref.lum=info.lum;
    state.ref.bg=info.bg;state.ref.sat=info.sat;
    if(!state.ref.strength)state.ref.strength="L2_material";
    renderRefPanel();renderPreflight();
    announce(`参考图已保存到投放区，并提取 ${info.palette.length} 个主色。`);
  }catch(error){announce("参考图处理失败："+errorMessage(error));}
  finally{setBusy(button,false,"上传参考图");$("refFile").value="";}
}
async function loadExistingRef(){
  try{
    const r=await api("/api/refs?sku="+encodeURIComponent(state.sku||"_未指定"));
    const items=r.items||[];
    if(!items.length){state.ref={rel:"",palette:[],strength:state.ref.strength||"L2_material"};renderRefPanel();return;}
    const newest=items[items.length-1];
    const img=await loadImage(passUrl(newest.rel));
    const info=extractPalette(img);
    state.ref.rel=newest.rel;state.ref.palette=info.palette;
    state.ref.lum=info.lum;state.ref.bg=info.bg;state.ref.sat=info.sat;
    renderRefPanel();
  }catch{state.ref={rel:"",palette:[],strength:"L2_material"};renderRefPanel();}
}

$("chooseRefButton")?.addEventListener("click",()=>$("refFile").click());
$("refFile")?.addEventListener("change",event=>uploadReference(event.target.files[0]));
$("refStrength")?.addEventListener("change",event=>{state.ref.strength=event.target.value;renderPreflight();});
$("applyPaletteButton")?.addEventListener("click",()=>{
  const p=(state.ref.palette||[])[0];
  if(!p)return;
  $("bodyColor").value=p.hex.toLowerCase();$("bodyColorValue").textContent=p.hex;
  announce(`主体色已设为参考图主色 ${p.hex}`);
});

/* =========================================================
   v2.2 优化升级（按 WINDOWS-AGENT 执行与验收文档 + 外层 ui 新版设计）
   ========================================================= */

/* --- 1) 键盘操作对比滑杆：左右方向键微调，Shift 加速 --- */
function wireCompareKeyboard(){
  const range=$("compareRange");
  if(!range)return;
  range.addEventListener("keydown",event=>{
    const step=event.shiftKey?10:2;
    if(event.key==="ArrowLeft"){event.preventDefault();range.value=String(Math.max(5,Number(range.value)-step));setComparePosition();}
    else if(event.key==="ArrowRight"){event.preventDefault();range.value=String(Math.min(95,Number(range.value)+step));setComparePosition();}
    else if(event.key==="Home"){event.preventDefault();range.value="5";setComparePosition();}
    else if(event.key==="End"){event.preventDefault();range.value="95";setComparePosition();}
  });
}

/* --- 2) 本轮执行与验收文档要求的「临时测试 SKU 守卫」---
   验收文档 §1.6 / §4 要求：运行时测试图必须放在明确标记的测试 SKU 下，
   且不得在原有生产 SKU 上做破坏性测试。这里把测试 SKU 统一口径写在前端。 */
const TEST_SKU_PREFIX="_";
function isTestSku(sku){return (sku||"").startsWith(TEST_SKU_PREFIX);}

/* --- 3) 服务离线时的下一步必须可执行 ---
   验收文档 §3.2：以启动窗口打印的 Web UI 地址为准，不要硬认 8765。
   这里改为提示「项目根目录的一键启动.bat」，不写死端口或已废弃的旧入口。 */
function offlineGuidance(){
  return "无法连接本地渲染服务。请双击项目根目录的「一键启动.bat」，"
       + "等启动窗口打印出 Web UI 地址后，回到本页点「刷新状态」。";
}

/* --- 4) 服务与扩展面板：三行能力说明随实际检测结果变化 --- */
function renderProviderPanel(){
  const comfy=state.comfy||{};
  const local=$("localProviderStatus"),cloud=$("cloudProviderStatus"),ref=$("referenceCapability");
  if(local){
    local.textContent=comfy.online
      ?`本地 ComfyUI：在线${comfy.version?" · "+comfy.version:""}${comfy.device?" · "+comfy.device:""}。结构约束与图片改图都走本机。`
      :"本地 ComfyUI：接口已接入，但服务当前未启动。";
  }
  if(cloud)cloud.textContent="云端图像 API：尚未配置，白模与产品图片只留在本机。";
  if(ref){
    ref.textContent=comfy.ipadapter_ok
      ?"参考图控制：已接入图像条件。参考图会作为条件参与生成，同时提取配色与影调；形状仍以白模为准。"
      :"参考图控制：未接入图像条件。当前只把参考图的配色与影调写进提示词，原图本身不参与生成。";
  }
}

/* --- 5) 数据一致性自检：把「界面说能出图」与「后端真能出图」对齐 ---
   验收文档 §6.2 提示过一个可观测性问题：服务端曾把图片任务也标成 txt2img。
   这里做一次轻量核对，只在控制台告警，不改动用户数据。 */
async function selfCheckProviders(){
  try{
    const [assets,comfy]=await Promise.all([api("/api/assets"),api("/api/comfy/status")]);
    const notes=[];
    if(comfy.online&&comfy.preferred_ok===false)notes.push("首选底模不可用，将自动切到兜底底模。");
    if(comfy.online&&!(comfy.controlnets||[]).length)notes.push("未发现 ControlNet 模型，结构约束模式无法出图。");
    const missing=(assets.items||[]).filter(item=>(item.views||[]).some(v=>!v.ok));
    if(missing.length)notes.push(`${missing.length} 个产品的部分机位结构图未齐备。`);
    if(notes.length)console.warn("[形照] 预检提示："+notes.join(" "));
    return notes;
  }catch{return [];}
}

wireCompareKeyboard();
setInterval(()=>{if(!document.hidden)renderProviderPanel();},15000);

refreshAll();
setInterval(()=>{if(!document.hidden)refreshTasks();},12000);
setInterval(()=>{if(!document.hidden)refreshServices();},30000);
