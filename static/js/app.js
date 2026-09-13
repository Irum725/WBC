// WBC Common Utilities

function copyText(elemId) {
    const el = document.getElementById(elemId);
    if (!el) return;
    navigator.clipboard.writeText(el.value || el.innerText).then(() => {
        alert('클립보드에 복사되었습니다! 카카오톡이나 SNS에 바로 붙여넣기 하세요.');
    }).catch(err => {
        console.error('복사 실패:', err);
        el.select();
        document.execCommand('copy');
        alert('복사되었습니다!');
    });
}
