import{j as r}from"./react-dom-BCtgtKsU.js";function f({color:s,size:e,x:a,y:n,blur:l,opacity:i=.18,animRange:t=30,duration:m=14}){const o=`glowOrbFloat-${t}`;return r.jsxs(r.Fragment,{children:[r.jsx("style",{children:`
        @keyframes ${o} {
          0%   { transform: translate(0, 0)                       scale(1);    }
          33%  { transform: translate(${t}px, -${t/2}px) scale(1.08); }
          66%  { transform: translate(-${t/2}px, ${t}px) scale(0.96); }
          100% { transform: translate(0, 0)                       scale(1);    }
        }
        @media (prefers-reduced-motion: reduce) {
          .glow-orb-anim { animation: none !important; }
        }
      `}),r.jsx("div",{className:"absolute rounded-full pointer-events-none glow-orb-anim",style:{width:e,height:e,left:a,top:n,background:s,filter:`blur(${l}px)`,opacity:i,animation:`${o} ${m}s ease-in-out infinite`}})]})}export{f as G};
