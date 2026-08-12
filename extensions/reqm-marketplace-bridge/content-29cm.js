function cellValue(row, headers, name) {
  const index = headers.findIndex(header => header.replace(/\s/g, "").includes(name));
  return index >= 0 ? (row.querySelectorAll("td")[index]?.innerText.trim() || "") : "";
}

chrome.runtime.onMessage.addListener((message, _sender, reply) => {
  if (message.type !== "REQM_READ_29CM_CATALOG") return;
  const rows = [...document.querySelectorAll("tbody tr")].map(row => {
    // 29CM 옵션 재고 화면의 고정 열 순서:
    // 체크박스, 상품번호, 이미지, 상품명, 브랜드, 옵션번호, 옵션명, 판매상태, 작업.
    // 헤더는 2단 구성이고 작업 열에는 '저장/판매중지' 버튼이 있어 이름으로 찾으면
    // 쉽게 어긋난다. td의 실제 위치를 사용한다.
    const cells = [...row.querySelectorAll(":scope > td")].map(cell => cell.innerText.trim());
    const text = index => cells[index] || "";
    return {
      marketplace_item_no: text(1),
      marketplace_option_no: text(5),
      marketplace_item_name: text(3),
      marketplace_option_name: text(6),
      sale_status: text(7),
      stock: [...row.querySelectorAll("input")][1]?.value || ""
    };
  }).filter(row => row.marketplace_item_no && row.marketplace_option_no && row.marketplace_item_name);
  reply({rows});
});
