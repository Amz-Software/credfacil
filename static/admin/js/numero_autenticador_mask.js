document.addEventListener('DOMContentLoaded', function () {
  var input = document.getElementById('id_numero');
  if (!input) return;

  input.setAttribute('placeholder', '(00) 00000-0000');
  input.setAttribute('maxlength', '16');

  input.addEventListener('input', function (e) {
    var value = e.target.value.replace(/\D/g, '').slice(0, 11);
    var formatted = '';
    if (value.length > 0) formatted = '(' + value.slice(0, 2);
    if (value.length > 2) formatted += ') ' + value.slice(2, 7);
    if (value.length > 7) formatted += '-' + value.slice(7, 11);
    e.target.value = formatted;
  });
});
