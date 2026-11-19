function formatarTexto(texto, div) {
    const data = JSON.parse(texto);
    let element;
    data.blocks.forEach(block => {
        switch(block.type) {
            case 'header':
                const level = block.data.level;
                element = document.createElement(`h${level}`);
                element.innerHTML = block.data.text;
                break;
            case 'list':
                const style = block.data.style;
                element = document.createElement(style === 'ordered' ? 'ol' : 'ul');
                block.data.items.forEach(item => {
                    const li = document.createElement('li');
                    li.innerHTML = item.content
                    element.appendChild(li);
                });
                break;
            case 'paragraph':
                element = document.createElement("p");
                element.innerHTML = block.data.text;
                break;
            default:
                // Tipo de bloco desconhecido: ignora.
                return;
        }
        div.appendChild(element);
    });
}