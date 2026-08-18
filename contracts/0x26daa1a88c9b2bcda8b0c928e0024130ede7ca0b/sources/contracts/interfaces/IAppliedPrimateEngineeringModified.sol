// SPDX-License-Identifier: MIT
pragma solidity ^0.8.17;

interface IAppliedPrimateEngineeringModified {
    function metadataKeys(uint256 id) external view returns (bytes32[] memory);
    function ownerOf(uint256 tokenId) external view returns (address owner);
}