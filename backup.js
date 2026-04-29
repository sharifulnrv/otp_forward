javascript:(function(){
    const e=document.getElementById("visa-master-dash"); e&&e.remove();
    const BASE_URL = "https://untold-playable-fanatic.ngrok-free.dev";
    let phoneNumber = localStorage.getItem("ivac_phone") || "01889106084";
    phoneNumber = prompt("Enter Phone Number to track:", phoneNumber);
    if(!phoneNumber) return;
    localStorage.setItem("ivac_phone", phoneNumber);
    const t=document.createElement("div");
    t.id="visa-master-dash";
    t.style="position:fixed;top:40px;right:20px;z-index:10000;background:#fff;border:3px solid #f58220;border-radius:16px;padding:20px;width:320px;box-shadow:0 10px 40px rgba(0,0,0,0.3);font-family:sans-serif;color:#000";
    t.innerHTML='<div style="font-weight:800;margin-bottom:6px;font-size:16px;text-align:center;color:#f58220">IVAC EXTRACTOR</div>' +
                '<div style="font-size:11px;text-align:center;color:#888;margin-bottom:10px;">Tracking: <b>' + phoneNumber + '</b></div>' +
                '<div id="status-msg" style="font-size:13px;text-align:center;color:#555;font-weight:bold;margin-top:6px">🔄 Auto-fetching OTP...</div>' +
                '<button id="stop-btn" style="margin-top:12px;width:100%;padding:10px;background:#e53935;color:#fff;border:none;border-radius:8px;font-weight:bold;font-size:13px;cursor:pointer">⏹ Stop</button>';
    document.body.appendChild(t);
    const statusEl=()=>document.getElementById("status-msg");
    let stopped=false, attempt=0, submitCount=0;
    document.getElementById("stop-btn").addEventListener("click",function(){ stopped=true; statusEl().innerText="⏹ Stopped."; });
    function fillOTP(otp){
        statusEl().style.color="#2e7d32";
        statusEl().innerText="✅ OTP Found: "+otp;
        otp.split("").forEach(function(v,i){
            const s=document.getElementById("otp-"+i)||document.getElementById("phoneOTP-"+i)||document.getElementById("emailOTP-"+i);
            if(s){
                s.focus();
                const a=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,"value").set;
                a.call(s,v);
                s.dispatchEvent(new Event("input",{bubbles:true}));
                s.dispatchEvent(new KeyboardEvent("keyup",{key:v,bubbles:true}));
            }
        });
        const clickVerify = function(){
            if(stopped) return;
            const b = document.querySelector('button[type="submit"]') || Array.from(document.querySelectorAll("button")).find(function(b){return b.textContent.includes("Verify")});
            if(b){
                submitCount++;
                b.click();
                statusEl().innerText = "🚀 Submitting... (Try #" + submitCount + ")";
                setTimeout(clickVerify, 2000);
            }
        };
        setTimeout(clickVerify, 500);
    }
    function tryFetch(){
        if(stopped) return;
        attempt++;
        statusEl().innerText="🔄 Attempt "+attempt+" — waiting...";
        fetch(BASE_URL + "/api/otp/" + phoneNumber, {
            headers:{"ngrok-skip-browser-warning":"1","Accept":"application/json"}
        })
        .then(function(r){return r.json()})
        .then(function(data){
            if(stopped) return;
            if(data.otp){
                stopped=true;
                fillOTP(data.otp);
            } else {
                setTimeout(tryFetch, 3000);
            }
        })
        .catch(function(){
            if(!stopped) setTimeout(tryFetch, 3000);
        });
    }
    tryFetch();
})();