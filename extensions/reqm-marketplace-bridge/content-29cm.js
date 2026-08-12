(() => {
  function readCatalog() {
    return [...document.querySelectorAll("tbody tr")].map(row => {
      // 상품번호는 행 헤더(th), 나머지는 td인 29CM 옵션 재고 화면 구조를 쓴다.
      const cells = [...row.querySelectorAll(":scope > th, :scope > td")].map(cell => cell.innerText.trim());
      const numeric = cells.filter(value => /^\d{6,}$/.test(value));
      const itemNo = numeric[0] || "";
      const optionNo = numeric[1] || "";
      const optionIndex = cells.indexOf(optionNo);
      return {
        marketplace_item_no: itemNo,
        marketplace_option_no: optionNo,
        marketplace_item_name: [...row.querySelectorAll("a")]
          .map(link => link.innerText.trim())
          .filter(value => value.length > 8 && !/^\d+$/.test(value))
          .sort((left, right) => right.length - left.length)[0] || "",
        marketplace_option_name: optionIndex >= 0 ? (cells[optionIndex + 1] || "") : "",
        sale_status: cells.find(value => value === "판매중" || value.startsWith("일시품절") || value === "판매중지") || "",
        stock: [...row.querySelectorAll("input")][1]?.value || ""
      };
    }).filter(row => row.marketplace_item_no && row.marketplace_option_no && row.marketplace_item_name);
  }

  // background.js가 매 동기화 시 최신 확장 코드를 강제로 주입한 뒤 직접 호출한다.
  globalThis.__REQM_READ_29CM_CATALOG = readCatalog;
  chrome.runtime.onMessage.addListener((message, _sender, reply) => {
    if (message.type === "REQM_READ_29CM_CATALOG") reply({rows: readCatalog()});
  });
})();
