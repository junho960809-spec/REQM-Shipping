function cellValue(row, headers, name) {
  const index = headers.findIndex(header => header.replace(/\s/g, "").includes(name));
  return index >= 0 ? (row.querySelectorAll("td")[index]?.innerText.trim() || "") : "";
}

chrome.runtime.onMessage.addListener((message, _sender, reply) => {
  if (message.type !== "REQM_READ_29CM_CATALOG") return;
  const rows = [...document.querySelectorAll("tbody tr")].map(row => {
    // 29CM은 상품번호를 td가 아닌 행 헤더(th)로 렌더링한다. 그래서 td 위치를
    // 고정하면 한 칸 밀린다. 행 전체(th+td)에서 첫 숫자는 상품번호, 두 번째 숫자는
    // 옵션번호로 잡고, 옵션번호 바로 다음 칸을 색상 옵션명으로 읽는다.
    const cells = [...row.querySelectorAll(":scope > th, :scope > td")].map(cell => cell.innerText.trim());
    const numeric = cells.filter(value => /^\d{6,}$/.test(value));
    const itemNo = numeric[0] || "";
    const optionNo = numeric[1] || "";
    const optionIndex = cells.indexOf(optionNo);
    const optionName = optionIndex >= 0 ? (cells[optionIndex + 1] || "") : "";
    const itemName = [...row.querySelectorAll("a")]
      .map(link => link.innerText.trim())
      .filter(value => value.length > 8 && !/^\d+$/.test(value))
      .sort((left, right) => right.length - left.length)[0] || "";
    return {
      marketplace_item_no: itemNo,
      marketplace_option_no: optionNo,
      marketplace_item_name: itemName,
      marketplace_option_name: optionName,
      sale_status: cells.find(value => value === "판매중" || value.startsWith("일시품절") || value === "판매중지") || "",
      stock: [...row.querySelectorAll("input")][1]?.value || ""
    };
  }).filter(row => row.marketplace_item_no && row.marketplace_option_no && row.marketplace_item_name);
  reply({rows});
});
