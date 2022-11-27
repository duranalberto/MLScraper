const todosList = document.getElementById("parent-container"); 
const input = document.getElementById("todo");
const statusScrape = document.getElementById("scrape-status");
const statusNewElement = document.getElementById("new-element");


const buttonInterval = document.getElementById("btn-interval");
const buttonIntervalStart = document.getElementById("btn-interval-start");
const buttonIntervalPause = document.getElementById("btn-interval-pause");

let initDate = null;

let nIntervId = null;
let isFetching = false;

const filterTime = 60000 * 60 * 10;
const highlightTime = 60000 * 30;
const intervalTime = 5000;
const soundlTime = 1000;


function fetchData() {
  if(isFetching) return;
  isFetching = true;
  fetch("/api/search")
    .then((response) => response.json())
    .then((json) => takeData(json))
    .then(() => isFetching = false);
} 

function performInterval(event) {
  event.preventDefault();
  if(nIntervId) {
    clearInterval(nIntervId);
    nIntervId = null;
    buttonIntervalPause.setAttribute('style','display: none;');
    buttonIntervalStart.setAttribute('style','');
    console.log('Clear interval ' + nIntervId)
    return;
  }
  buttonIntervalStart.setAttribute('style','display: none;');
  buttonIntervalPause.setAttribute('style','');
  nIntervId = setInterval(fetchData, intervalTime);
  console.log('Init interval ' + nIntervId);
  fetchData();
}

function takeData(val) {
  initDate = Date.now();
  innerHTML = '';
  val.map(term => innerHTML += renderData(term));
  todosList.innerHTML = innerHTML;
}
  
function renderData(dataSlice) {
  let list = dataSlice["elements"]
  .filter(todo => {
    const tD = initDate - Date.parse(todo.datetime);
    return tD < filterTime;
  })
  .map(todo =>{
      const dateText = new Date(todo.datetime).toLocaleString();
      const tD = initDate - Date.parse(todo.datetime);
      const isNew = tD < highlightTime ? 'new-element' : '';
      if( tD < soundlTime ) do_sound();
      return `<div class="article ${isNew}">
                <div class="details">
                  <div class="date">${dateText}</div>
                  <div class="price">$${todo.price}</div>
                </div>
                <div class="title">
                  <a href="https://articulo.mercadolibre.com.mx/${todo.identifier}">${todo.title}</a>
                </div>
              </div>`;
    }
  )
  .join(" ");
  return list !== "" ? 
    `<div class="container">
      <h2>${dataSlice["title"]}</h2>
      <div class="l-articles">${list}</div>
    </div>` : ' ';
}

function manageStatus(response) {
  obj = JSON.parse(response)
  if(obj == null)  return;
  if(obj['message'] == 'scrape status') {
    fetchData();
    statusScrape.innerHTML = obj['payload']
  }
  if(obj['message'] == 'new element' && obj['payload']) {
    do_sound();
    fetchData();
    statusNewElement.innerHTML  = 'New ' + obj['payload']['search_term'] 
                                + ' : ' + obj['payload']['title']
                                + ' - ' + obj['payload']['price'];
  }
}


function do_sound() {
  let src = '/notification.wav';
  let audio = new Audio(src);
  audio.play();
}

fetchData();
buttonInterval.addEventListener("click", performInterval);

var ws = new WebSocket('ws://localhost/ws/');
ws.onmessage = function(event) {
  console.log(event.data);
  manageStatus(event.data);
};

//do_sound();