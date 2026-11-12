(async()=>{
 const el=document.getElementById('map');if(!el||!window.L)return;
 // Approximate campus map centre; live vehicle positions always come from driver GPS.
 const campus=[8.25,77.55];
 const map=L.map(el,{zoomControl:true}).setView(campus,9);
 L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap &copy; CARTO'}).addTo(map);
 const campusIcon=L.divIcon({className:'campus-marker',html:'<span>🏫</span>',iconSize:[34,34],iconAnchor:[17,17]});
 L.marker(campus,{icon:campusIcon}).addTo(map).bindPopup('<b>CampusMove Hub</b><br>Joy University · Vadakkankulam');
 const markers={};
 async function refresh(){try{const res=await fetch('/api/trips');if(!res.ok)return;const trips=await res.json();trips.forEach(t=>{if(t.latitude==null||t.longitude==null)return;const pos=[t.latitude,t.longitude];if(markers[t.id])markers[t.id].setLatLng(pos);else{const icon=L.divIcon({className:'bus-marker',html:'<span>🚌</span>',iconSize:[38,38],iconAnchor:[19,19]});markers[t.id]=L.marker(pos,{icon}).addTo(map);}markers[t.id].bindPopup(`<b>${t.bus_number}</b><br>${t.route_name||'Campus route'}<br>Speed: ${(Number(t.speed||0)*3.6).toFixed(1)} km/h<br><small>Last update: ${t.recorded_at||'—'}</small>`);});}catch(e){console.error('Live fleet refresh failed',e)}}
 await refresh();setInterval(refresh,5000);
})();
