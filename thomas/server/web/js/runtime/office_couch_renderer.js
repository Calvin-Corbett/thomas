/** Draft-office couch renderer. */

function officeDraftCreateCouchElement(space, asset, state) {
    const descriptor = officeDraftAssetDimensions('couch', asset?.scale);
    const couchColor = officeDraftAssetColorway('couch', asset?.colorVariant);
    const scale = descriptor.scale;
    const scaled = (value) => `${Math.round(Number(value) * scale)}px`;
    const couch = document.createElement('div');
    const isSelected = state.editorOpen && safeString(asset?.id) === safeString(state.selectedAssetId);
    const rotation = officeDraftNormalizeRotation(asset?.rotation);
    const isPreview = Boolean(asset?.preview);
    couch.dataset.officeDraftAssetId = safeString(asset?.id);
    couch.dataset.officeDraftSpaceId = safeString(space?.id);
    couch.dataset.officeDraftAssetType = 'couch';
    couch.style.position = 'absolute';
    couch.style.left = `${Math.round(Number(asset?.x) || 0)}px`;
    couch.style.top = `${Math.round(Number(asset?.y) || 0)}px`;
    couch.style.width = `${descriptor.width}px`;
    couch.style.height = `${descriptor.height}px`;
    couch.style.pointerEvents = isPreview ? 'none' : (state.editorOpen ? 'auto' : 'none');
    couch.style.cursor = isPreview ? 'copy' : (state.editorOpen ? (isSelected && state.assetPointerId !== null ? 'grabbing' : 'grab') : 'default');
    couch.style.filter = isPreview ? 'opacity(0.72) drop-shadow(0 0 0.55rem rgba(111, 169, 255, 0.38))' : (isSelected ? 'drop-shadow(0 0 0.65rem rgba(111, 169, 255, 0.45))' : 'none');
    couch.style.outline = isPreview ? '2px dashed rgba(132, 187, 255, 0.6)' : (isSelected ? '2px solid rgba(132, 187, 255, 0.75)' : 'none');
    couch.style.outlineOffset = scaled(4);
    couch.style.borderRadius = scaled(22);
    couch.style.transform = `rotate(${rotation}deg)`;
    couch.style.transformOrigin = 'center center';

    const couchShadow = document.createElement('div');
    couchShadow.style.position = 'absolute';
    couchShadow.style.left = scaled(18);
    couchShadow.style.top = scaled(142);
    couchShadow.style.width = scaled(300);
    couchShadow.style.height = scaled(18);
    couchShadow.style.borderRadius = '999px';
    couchShadow.style.background = 'rgba(3, 8, 16, 0.18)';
    couch.appendChild(couchShadow);

    const couchBack = document.createElement('div');
    couchBack.style.position = 'absolute';
    couchBack.style.left = scaled(30);
    couchBack.style.top = scaled(12);
    couchBack.style.width = scaled(276);
    couchBack.style.height = scaled(88);
    couchBack.style.borderRadius = `${scaled(24)} ${scaled(24)} ${scaled(18)} ${scaled(18)}`;
    couchBack.style.background = couchColor.back;
    couchBack.style.boxShadow = 'inset 0 8px 12px rgba(255, 240, 224, 0.18), inset 0 -8px 12px rgba(79, 40, 17, 0.18)';
    couch.appendChild(couchBack);

    const couchSeat = document.createElement('div');
    couchSeat.style.position = 'absolute';
    couchSeat.style.left = scaled(18);
    couchSeat.style.top = scaled(72);
    couchSeat.style.width = scaled(300);
    couchSeat.style.height = scaled(74);
    couchSeat.style.borderRadius = scaled(22);
    couchSeat.style.background = couchColor.seat;
    couchSeat.style.boxShadow = 'inset 0 8px 10px rgba(255, 239, 219, 0.18), inset 0 -10px 14px rgba(105, 58, 28, 0.2)';
    couch.appendChild(couchSeat);

    const couchArmLeft = document.createElement('div');
    couchArmLeft.style.position = 'absolute';
    couchArmLeft.style.left = '0';
    couchArmLeft.style.top = scaled(54);
    couchArmLeft.style.width = scaled(58);
    couchArmLeft.style.height = scaled(84);
    couchArmLeft.style.borderRadius = scaled(20);
    couchArmLeft.style.background = couchColor.arm;
    couchArmLeft.style.boxShadow = 'inset 0 6px 9px rgba(255, 229, 209, 0.12)';
    couch.appendChild(couchArmLeft);

    const couchArmRight = document.createElement('div');
    couchArmRight.style.position = 'absolute';
    couchArmRight.style.right = '0';
    couchArmRight.style.top = scaled(54);
    couchArmRight.style.width = scaled(58);
    couchArmRight.style.height = scaled(84);
    couchArmRight.style.borderRadius = scaled(20);
    couchArmRight.style.background = couchColor.arm;
    couchArmRight.style.boxShadow = 'inset 0 6px 9px rgba(255, 229, 209, 0.12)';
    couch.appendChild(couchArmRight);

    const couchSeamLeft = document.createElement('div');
    couchSeamLeft.style.position = 'absolute';
    couchSeamLeft.style.left = scaled(122);
    couchSeamLeft.style.top = scaled(82);
    couchSeamLeft.style.width = scaled(2);
    couchSeamLeft.style.height = scaled(48);
    couchSeamLeft.style.background = couchColor.seam;
    couch.appendChild(couchSeamLeft);

    const couchSeamRight = document.createElement('div');
    couchSeamRight.style.position = 'absolute';
    couchSeamRight.style.left = scaled(214);
    couchSeamRight.style.top = scaled(82);
    couchSeamRight.style.width = scaled(2);
    couchSeamRight.style.height = scaled(48);
    couchSeamRight.style.background = couchColor.seam;
    couch.appendChild(couchSeamRight);

    return couch;
}


