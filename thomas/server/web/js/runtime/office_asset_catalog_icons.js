/** Office asset-catalog icon markup. */

function officeDraftCatalogIconMarkup(assetType, color = {}) {
    const descriptor = OFFICE_DRAFT_ASSET_LIBRARY[safeString(assetType)] || {};
    const shape = safeString(descriptor.shape);
    const body = color.body || color.back || color.swatch || 'linear-gradient(180deg, #7aa7d9, #435b86)';
    const surface = color.surface || color.seat || body;
    const accent = color.accent || color.arm || 'rgba(225, 241, 255, 0.92)';
    const line = color.line || color.seam || 'rgba(12, 20, 34, 0.45)';
    const shadow = '<span style="position:absolute;left:16px;right:16px;bottom:5px;height:5px;border-radius:999px;background:rgba(2,7,14,0.26);"></span>';
    if (assetType === 'couch') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:20px;top:8px;width:72px;height:24px;border-radius:13px 13px 8px 8px;background:${body};"></span><span style="position:absolute;left:10px;top:26px;width:92px;height:24px;border-radius:14px;background:${surface};"></span><span style="position:absolute;left:0;top:22px;width:22px;height:28px;border-radius:10px;background:${accent};"></span><span style="position:absolute;right:0;top:22px;width:22px;height:28px;border-radius:10px;background:${accent};"></span></span>`;
    }
    if (assetType === 'desk') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:12px;top:20px;width:88px;height:22px;border-radius:9px;background:${surface};"></span><span style="position:absolute;left:24px;top:40px;width:12px;height:18px;border-radius:4px;background:${body};"></span><span style="position:absolute;right:24px;top:40px;width:12px;height:18px;border-radius:4px;background:${body};"></span><span style="position:absolute;left:62px;top:28px;width:24px;height:4px;border-radius:999px;background:${accent};"></span></span>`;
    }
    if (assetType === 'chair') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:42px;top:8px;width:30px;height:30px;border-radius:12px 12px 6px 6px;background:${body};"></span><span style="position:absolute;left:34px;top:34px;width:46px;height:18px;border-radius:10px;background:${surface};"></span><span style="position:absolute;left:40px;top:50px;width:5px;height:12px;background:${line};"></span><span style="position:absolute;right:40px;top:50px;width:5px;height:12px;background:${line};"></span></span>`;
    }
    if (assetType === 'workstation') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:20px;top:42px;width:72px;height:14px;border-radius:7px;background:${surface};"></span><span style="position:absolute;left:32px;top:10px;width:48px;height:34px;border-radius:7px;background:rgba(7,12,22,0.82);border:5px solid ${body};"></span><span style="position:absolute;left:43px;top:23px;width:26px;height:6px;border-radius:999px;background:${accent};box-shadow:0 0 10px ${accent};"></span></span>`;
    }
    if (assetType === 'whiteboard') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:16px;top:10px;width:80px;height:38px;border-radius:8px;background:${surface};border:5px solid ${body};"></span><span style="position:absolute;left:32px;top:27px;width:28px;height:3px;border-radius:999px;background:${accent};"></span><span style="position:absolute;left:32px;top:36px;width:48px;height:3px;border-radius:999px;background:${line};"></span></span>`;
    }
    if (assetType === 'vending_machine') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:40px;top:4px;width:34px;height:56px;border-radius:9px;background:${body};"></span><span style="position:absolute;left:48px;top:14px;width:14px;height:24px;border-radius:4px;background:rgba(231,246,255,0.68);"></span><span style="position:absolute;left:47px;top:42px;width:20px;height:10px;border-radius:5px;background:${accent};"></span><span style="position:absolute;right:39px;top:16px;width:7px;height:24px;border-radius:3px;background:${line};"></span></span>`;
    }
    if (assetType === 'coffee_bar') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:14px;top:32px;width:84px;height:22px;border-radius:10px;background:${body};"></span><span style="position:absolute;left:22px;top:22px;width:68px;height:16px;border-radius:8px;background:${surface};"></span><span style="position:absolute;left:34px;top:8px;width:12px;height:16px;border-radius:4px 4px 8px 8px;background:${accent};"></span><span style="position:absolute;left:54px;top:6px;width:20px;height:20px;border-radius:6px;background:${line};"></span></span>`;
    }
    if (assetType === 'round_table') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:35px;top:9px;width:42px;height:42px;border-radius:999px;background:${surface};box-shadow:inset 0 -8px rgba(0,0,0,0.14);"></span><span style="position:absolute;left:50px;top:24px;width:12px;height:12px;border-radius:999px;background:${body};"></span></span>`;
    }
    if (assetType === 'plant') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:46px;bottom:9px;width:20px;height:18px;border-radius:6px 6px 10px 10px;background:${accent};"></span><span style="position:absolute;left:38px;top:18px;width:22px;height:34px;border-radius:70% 30% 70% 30%;background:${surface};transform:rotate(-25deg);"></span><span style="position:absolute;left:54px;top:8px;width:24px;height:42px;border-radius:45% 65% 45% 65%;background:${body};transform:rotate(15deg);"></span></span>`;
    }
    if (assetType === 'bookshelf') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:24px;top:9px;width:64px;height:48px;border-radius:8px;background:${body};"></span><span style="position:absolute;left:32px;top:24px;width:48px;height:3px;background:${line};"></span><span style="position:absolute;left:32px;top:40px;width:48px;height:3px;background:${line};"></span><span style="position:absolute;left:36px;top:28px;width:5px;height:10px;background:${accent};"></span><span style="position:absolute;left:48px;top:28px;width:5px;height:10px;background:${surface};"></span><span style="position:absolute;left:60px;top:44px;width:5px;height:10px;background:${accent};"></span></span>`;
    }
    if (assetType === 'server_rack') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:40px;top:5px;width:34px;height:54px;border-radius:8px;background:${body};border:4px solid rgba(5,10,18,0.5);"></span><span style="position:absolute;left:49px;top:18px;width:16px;height:5px;border-radius:3px;background:${surface};"></span><span style="position:absolute;left:49px;top:30px;width:16px;height:5px;border-radius:3px;background:${surface};"></span><span style="position:absolute;right:45px;top:19px;width:4px;height:4px;border-radius:999px;background:${accent};box-shadow:0 0 8px ${accent};"></span></span>`;
    }
    if (assetType === 'focus_pod') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:34px;top:6px;width:44px;height:54px;border-radius:24px 24px 12px 12px;background:${body};"></span><span style="position:absolute;left:43px;top:19px;width:26px;height:30px;border-radius:16px 16px 8px 8px;background:${surface};"></span><span style="position:absolute;left:49px;top:30px;width:14px;height:4px;border-radius:999px;background:${accent};"></span></span>`;
    }
    if (shape === 'counter' || shape === 'bench') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:10px;top:25px;width:92px;height:24px;border-radius:10px;background:${surface};"></span><span style="position:absolute;left:18px;top:44px;width:12px;height:14px;border-radius:4px;background:${body};"></span><span style="position:absolute;right:18px;top:44px;width:12px;height:14px;border-radius:4px;background:${body};"></span><span style="position:absolute;left:28px;top:32px;width:56px;height:5px;border-radius:999px;background:${accent};"></span></span>`;
    }
    if (shape === 'table' || shape === 'tilt_table') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:14px;top:20px;width:84px;height:28px;border-radius:${shape === 'tilt_table' ? '8px 18px 8px 18px' : '16px'};background:${surface};transform:${shape === 'tilt_table' ? 'skewX(-10deg)' : 'none'};"></span><span style="position:absolute;left:36px;top:44px;width:7px;height:14px;background:${body};"></span><span style="position:absolute;right:36px;top:44px;width:7px;height:14px;background:${body};"></span></span>`;
    }
    if (shape === 'screen' || shape === 'board') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:20px;top:10px;width:72px;height:40px;border-radius:8px;background:${shape === 'screen' ? 'rgba(5,10,18,0.86)' : surface};border:5px solid ${body};"></span><span style="position:absolute;left:35px;top:24px;width:42px;height:5px;border-radius:999px;background:${accent};box-shadow:${shape === 'screen' ? `0 0 10px ${accent}` : 'none'};"></span><span style="position:absolute;left:35px;top:36px;width:30px;height:4px;border-radius:999px;background:${line};"></span></span>`;
    }
    if (shape === 'cabinet' || shape === 'shelf') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:34px;top:8px;width:44px;height:50px;border-radius:8px;background:${body};"></span><span style="position:absolute;left:40px;top:23px;width:32px;height:3px;background:${line};"></span><span style="position:absolute;left:40px;top:38px;width:32px;height:3px;background:${line};"></span><span style="position:absolute;left:44px;top:27px;width:6px;height:9px;background:${accent};"></span><span style="position:absolute;left:58px;top:42px;width:6px;height:9px;background:${surface};"></span></span>`;
    }
    if (shape === 'appliance' || shape === 'machine' || shape === 'console') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:26px;top:20px;width:60px;height:32px;border-radius:9px;background:${body};"></span><span style="position:absolute;left:36px;top:28px;width:28px;height:10px;border-radius:4px;background:${surface};"></span><span style="position:absolute;right:32px;top:30px;width:7px;height:7px;border-radius:999px;background:${accent};box-shadow:0 0 8px ${accent};"></span></span>`;
    }
    if (shape === 'tower' || shape === 'lamp' || shape === 'light' || shape === 'tripod' || shape === 'sign') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:50px;top:18px;width:10px;height:36px;border-radius:6px;background:${body};"></span><span style="position:absolute;left:38px;top:${shape === 'lamp' || shape === 'light' ? '7px' : '12px'};width:34px;height:${shape === 'sign' ? '22px' : '20px'};border-radius:${shape === 'sign' ? '5px' : '12px'};background:${surface};box-shadow:0 0 10px ${accent};"></span><span style="position:absolute;left:32px;top:53px;width:48px;height:5px;border-radius:999px;background:${line};"></span></span>`;
    }
    if (shape === 'cart' || shape === 'dock' || shape === 'node' || shape === 'box') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:28px;top:25px;width:56px;height:24px;border-radius:8px;background:${surface};border:4px solid ${body};"></span><span style="position:absolute;left:38px;top:48px;width:8px;height:8px;border-radius:999px;background:${line};"></span><span style="position:absolute;right:38px;top:48px;width:8px;height:8px;border-radius:999px;background:${line};"></span><span style="position:absolute;left:46px;top:33px;width:20px;height:5px;border-radius:999px;background:${accent};"></span></span>`;
    }
    if (shape === 'panel' || shape === 'divider' || shape === 'rug' || shape === 'soft_seat') {
        return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:${shape === 'rug' ? '16px' : '34px'};top:${shape === 'rug' ? '21px' : '12px'};width:${shape === 'rug' ? '80px' : '44px'};height:${shape === 'rug' ? '32px' : '42px'};border-radius:${shape === 'soft_seat' ? '999px 999px 18px 18px' : '12px'};background:${surface};border:4px solid ${body};"></span><span style="position:absolute;left:44px;top:31px;width:24px;height:5px;border-radius:999px;background:${accent};"></span></span>`;
    }
    return `<span style="position:relative;display:block;width:112px;height:64px;">${shadow}<span style="position:absolute;left:30px;top:14px;width:52px;height:36px;border-radius:12px;background:${surface};border:5px solid ${body};"></span></span>`;
}


